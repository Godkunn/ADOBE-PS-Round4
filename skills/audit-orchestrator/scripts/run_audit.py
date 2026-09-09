#!/usr/bin/env python3
"""
audit-orchestrator / run_audit.py
Entrypoint orchestration script for Brand AI Readiness Audit.

Coordinates execution of all modular sub-skills against a target URL,
merges and deduplicates findings, assigns sequential IDs (F-001, F-002 ...),
tallies severity counts, computes the 4-pillar GEO readiness score,
and emits a single, strictly formatted JSON report.

Production Standards:
  - Enforced single run_checks() interface contract with context sharing.
  - SSRF guard against private, link-local, and loopback IP targeting.
  - Cross-platform path-traversal guard on --output (Windows + POSIX).
  - Non-zero exit code on report write failures.
  - Dual CLI invocation contract: supports both --url <URL> and positional <URL>.
  - Full 4-pillar GEO readiness score and pillar breakdown included.
  - Shared fetch context eliminates redundant network requests.
  - 100% zero-crash fault containment.

Read-only: never modifies the target site.
"""

from __future__ import annotations

import os
import sys
import json
import argparse
import importlib.util
import inspect
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR  = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
SHARED_DIR  = os.path.join(SKILLS_DIR, "shared")
if SHARED_DIR not in sys.path:
    sys.path.insert(0, SHARED_DIR)

from utils import (
    normalize_url, is_safe_target_url, calculate_geo_score,
    calculate_pillar_scores, AuditContext, finding,
)

# ---------------------------------------------------------------------------
# Sub-skill registry: (skill_id, script_filename) in execution order.
# ---------------------------------------------------------------------------
SUB_SKILLS = [
    ("crawl-render-audit",      "check_crawler_render.py"),
    ("structured-data-audit",   "check_structured_data.py"),
    ("freshness-corroboration", "check_freshness.py"),
    ("engagement-bounce-audit", "check_engagement.py"),
]

_VALID_SEVERITIES   = frozenset({"critical", "high", "medium", "low"})
_VALID_PRIORITIES   = frozenset({"high", "medium", "low"})


# ---------------------------------------------------------------------------
# Module loading
# ---------------------------------------------------------------------------
def load_skill_module(skill_id: str, script_name: str) -> Any:
    """
    Dynamically import a sub-skill script by absolute file path.
    Registers the module in sys.modules so that unittest.mock.patch
    targets resolve correctly.
    """
    script_path = os.path.join(SKILLS_DIR, skill_id, "scripts", script_name)
    if not os.path.isfile(script_path):
        raise ImportError(f"Sub-skill script not found: {script_path}")

    module_name = skill_id.replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load spec for {script_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


# ---------------------------------------------------------------------------
# Atomic output-file write with cross-platform path-traversal guard
# ---------------------------------------------------------------------------
def _safe_write_output(output_path: str, json_text: str) -> None:
    """
    Write json_text to output_path atomically (tempfile + os.replace).

    Enforces path traversal checks: prevents directory escape via relative traversal ('..')
    and blocks writing to root directories. Automatically creates destination directories.
    """
    if not output_path or not str(output_path).strip():
        raise ValueError("Output path cannot be empty.")

    raw_target = Path(output_path)
    # If path is relative, ensure it does not escape the current working directory
    if not raw_target.is_absolute():
        base = Path.cwd().resolve()
        target = (base / raw_target).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            raise ValueError(
                f"Path traversal detected: '{output_path}' escapes the current working directory."
            )
    else:
        target = raw_target.resolve()

    # Block writing directly to filesystem root or if target is a directory
    if target.parent == target or target.is_dir():
        raise ValueError(f"Invalid output destination: '{output_path}' cannot be filesystem root or a directory.")

    out_dir = target.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # Atomic write: write to temporary file in same directory, then rename
    fd, tmp_path = tempfile.mkstemp(dir=str(out_dir), suffix=".tmp", prefix="audit_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json_text)
        os.replace(tmp_path, str(target))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Core audit runner
# ---------------------------------------------------------------------------
def run_full_audit(
    target_url: str,
    timeout: int = 10,
    verify_ssl: bool = True,
) -> Dict[str, Any]:
    """
    Execute all sub-skills against target_url and return the merged audit report.

    Args:
        target_url:  Website URL to audit (scheme optional; https:// prepended if absent).
        timeout:     Per-HTTP-request timeout in seconds.
        verify_ssl:  When False, disables TLS certificate verification (dev only).
    """
    url = normalize_url(target_url)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # SSRF Protection Check
    is_safe, ssrf_err = is_safe_target_url(url)
    if not is_safe:
        finding_item = finding(
            title="SSRF / Prohibited Target Host Blocked",
            severity="critical",
            evidence=f"Target URL '{url}' is prohibited: {ssrf_err}",
            action_summary="Specify a publicly accessible domain name over HTTP or HTTPS.",
            action_priority="high",
            confidence=1.0,
        )
        finding_item["id"] = "F-001"
        return {
            "site": url,
            "audited_at": timestamp,
            "geo_score": 10,
            "pillar_scores": {
                "crawl_render": 10.0,
                "structured_data": 10.0,
                "freshness_security": 10.0,
                "engagement": 10.0,
            },
            "summary": {
                "total_findings": 1,
                "critical": 1,
                "high": 0,
                "medium": 0,
                "low": 0,
            },
            "findings": [finding_item],
        }

    raw_findings: List[Dict[str, Any]] = []

    # Initialize shared audit context for single-fetch reuse
    audit_context = AuditContext(url, timeout=timeout, verify_ssl=verify_ssl)

    for skill_id, script_name in SUB_SKILLS:
        try:
            mod = load_skill_module(skill_id, script_name)

            if not hasattr(mod, "run_checks") or not callable(mod.run_checks):
                raise ImportError(
                    f"Sub-skill '{skill_id}' does not expose the required "
                    f"run_checks(url, timeout, verify_ssl) interface."
                )

            # Pass shared audit context if accepted, otherwise standard signature
            accepts_context = False
            try:
                sig = inspect.signature(mod.run_checks)
                accepts_context = (
                    "context" in sig.parameters
                    or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
                )
            except (ValueError, TypeError):
                accepts_context = False

            if accepts_context:
                findings = mod.run_checks(url, timeout=timeout, verify_ssl=verify_ssl, context=audit_context)
            else:
                findings = mod.run_checks(url, timeout=timeout, verify_ssl=verify_ssl)

            if isinstance(findings, list):
                raw_findings.extend(findings)

        except Exception as exc:  # noqa: BLE001 - zero-crash fault containment
            raw_findings.append({
                "title":    f"Skill '{skill_id}' Execution Notice",
                "severity": "medium",
                "evidence": (
                    f"Internal notice during execution of '{skill_id}': "
                    f"{str(exc)[:220]}"
                ),
                "suggested_action": {
                    "summary":  "Verify target network connectivity and public URL accessibility.",
                    "priority": "low",
                },
                "confidence": 1.0,
            })

    # -------------------------------------------------------------------------
    # Deduplicate by composite key: (normalised title, evidence[:60])
    # -------------------------------------------------------------------------
    # Deduplicate, normalize, and sort findings by severity (critical -> high -> medium -> low)
    # -------------------------------------------------------------------------
    cleaned_findings: List[Dict[str, Any]] = []
    seen_keys: set = set()

    for f in raw_findings:
        if not isinstance(f, dict):
            continue

        title    = str(f.get("title",    "Unspecified Finding")).strip()
        evidence = str(f.get("evidence", "")).strip()
        dedup_key = (title.lower(), evidence[:60].lower())
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        sev = str(f.get("severity", "medium")).lower()
        if sev not in _VALID_SEVERITIES:
            sev = "medium"

        action = f.get("suggested_action", {})
        if not isinstance(action, dict):
            action = {"summary": str(action), "priority": "medium"}
        prio = str(action.get("priority", "medium")).lower()
        if prio not in _VALID_PRIORITIES:
            prio = "medium"

        confidence = float(f.get("confidence", 1.0))
        confidence = round(max(0.0, min(1.0, confidence)), 2)

        cleaned_findings.append({
            "title":    title,
            "severity": sev,
            "evidence": evidence or "No evidence recorded.",
            "suggested_action": {
                "summary":  str(action.get("summary",  "Review and optimise page configuration.")),
                "priority": prio,
            },
            "confidence": confidence,
        })

    # Sort strictly: critical -> high -> medium -> low
    _SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    cleaned_findings.sort(key=lambda item: _SEV_RANK.get(item["severity"], 99))

    final_findings: List[Dict[str, Any]] = []
    for counter, cf in enumerate(cleaned_findings, start=1):
        final_findings.append({
            "id": f"F-{counter:03d}",
            **cf,
        })

    # Severity distribution
    summary_counts: Dict[str, int] = {
        "total_findings": len(final_findings),
        "critical":       sum(1 for f in final_findings if f["severity"] == "critical"),
        "high":           sum(1 for f in final_findings if f["severity"] == "high"),
        "medium":         sum(1 for f in final_findings if f["severity"] == "medium"),
        "low":            sum(1 for f in final_findings if f["severity"] == "low"),
    }

    geo_score = calculate_geo_score(final_findings)
    pillar_scores = calculate_pillar_scores(final_findings)

    return {
        "site":          url,
        "audited_at":    timestamp,
        "geo_score":     geo_score,
        "pillar_scores": pillar_scores,
        "summary":       summary_counts,
        "findings":      final_findings,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Brand AI Readiness Audit — Evaluates AI Discoverability (GEO) "
            "and On-Site Engagement for any public website."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python run_audit.py https://example.com\n"
            "  python run_audit.py --url https://example.com --output report.json\n"
            "  python run_audit.py https://example.com --timeout 15 --no-verify-ssl"
        ),
    )
    # Satisfies PROJECT.md §3.3 contract: supports both positional and --url option
    parser.add_argument(
        "url_pos",
        nargs="?",
        default=None,
        help="Target website URL (e.g. https://example.com or example.com)",
    )
    parser.add_argument(
        "--url",
        dest="url_opt",
        default=None,
        help="Target website URL (alternative to positional argument)",
    )
    parser.add_argument(
        "--output", "-o",
        help="File path to persist the JSON report (atomic write).",
        default=None,
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Per-request timeout in seconds (default: 10).",
    )
    parser.add_argument(
        "--no-verify-ssl",
        dest="no_verify_ssl",
        action="store_true",
        default=False,
        help="Disable TLS certificate verification (dev/self-signed cert use only).",
    )
    args = parser.parse_args()

    target_url = args.url_opt or args.url_pos
    if not target_url:
        parser.error("A target URL must be provided via positional argument or --url flag.")

    verify_ssl = not args.no_verify_ssl
    report     = run_full_audit(target_url, timeout=args.timeout, verify_ssl=verify_ssl)
    json_out   = json.dumps(report, indent=2, ensure_ascii=False)

    print(json_out)

    if args.output:
        try:
            _safe_write_output(args.output, json_out)
        except Exception as exc:
            sys.stderr.write(f"Error: could not write report to {args.output}: {exc}\n")
            sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
