#!/usr/bin/env python3
"""
crawl-render-audit / check_crawler_render.py

Audits website accessibility for AI web crawlers:
  - robots.txt: RFC 9309-compliant parser with Allow: override and Crawl-Delay.
  - WAF / CDN bot-blocking probe via GPTBot user-agent.
  - Anti-bot challenge signatures (Cloudflare Turnstile, reCAPTCHA, DataDome, etc.).
  - Client-Side Rendering (CSR) vs Server-Side Rendering (SSR) heuristics.

Production Refinements:
  - Dual CLI argument support: positional <URL> and --url <URL> (PROJECT.md §3.3).
  - Shared AuditContext support to eliminate redundant network round-trips.
  - Calibrated robots.txt severity: only root / blockage is critical.
  - Confidence scores on every finding.

Read-only: GET requests only, never modifies the target site.
"""

from __future__ import annotations

import os
import sys
import json
import re
import argparse
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

_SHARED_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "shared")
)
if _SHARED_DIR not in sys.path:
    sys.path.insert(0, _SHARED_DIR)
from utils import (
    normalize_url, domain_root, polite_get, make_session, finding, current_year,
    AuditContext, HEADERS_BROWSER,
)

try:
    from bs4 import BeautifulSoup
except ImportError as exc:  # pragma: no cover
    raise ImportError("beautifulsoup4 is required: pip install beautifulsoup4") from exc

DEFAULT_TIMEOUT = 10

HEADERS_AIBOT: Dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (compatible; GPTBot/1.2; +https://openai.com/gptbot)",
}

AI_BOTS: List[str] = [
    "GPTBot",
    "ChatGPT-User",
    "OAI-SearchBot",
    "PerplexityBot",
    "ClaudeBot",
    "Claude-Web",
    "Claude-User",
    "Claude-SearchBot",
    "Google-Extended",
    "Applebot-Extended",
    "Amazonbot",
    "CCBot",
    "anthropic-ai",
    "cohere-ai",
    "Bytespider",
]

MAJOR_AI_BOTS: set = {
    "gptbot",
    "chatgpt-user",
    "oai-searchbot",
    "perplexitybot",
    "claudebot",
    "claude-web",
    "claude-user",
    "claude-searchbot",
    "google-extended",
    "applebot-extended",
}

CORE_AI_SEARCH_BOTS: set = {
    "gptbot",
    "chatgpt-user",
    "oai-searchbot",
    "perplexitybot",
    "claudebot",
    "claude-user",
    "claude-searchbot",
    "google-extended",
}

SPA_ROOT_SELECTOR = "#root, #app, #__next, #___gatsby, #main-app, #react-root"

ANTIBOT_SIGNATURES: Dict[str, List[str]] = {
    "Cloudflare Turnstile": [
        r"challenges\.cloudflare\.com/turnstile",
        r"cf-turnstile",
    ],
    "Google reCAPTCHA": [
        r"google\.com/recaptcha",
        r"recaptcha/api\.js",
        r"g-recaptcha",
    ],
    "hCaptcha": [
        r"hcaptcha\.com/1/api\.js",
        r"h-captcha",
    ],
    "DataDome / PerimeterX": [
        r"datadome\.co",
        r"px-cdn\.net",
        r"_pxAppId",
    ],
    "AWS WAF Bot Control": [
        r"awswaf",
        r"aws-waf-token",
    ],
}


# ---------------------------------------------------------------------------
# robots.txt parser — RFC 9309-compliant
# ---------------------------------------------------------------------------
def parse_robots_txt(robots_text: str) -> Dict[str, Dict[str, Any]]:
    rules: Dict[str, Dict[str, Any]] = {}
    current_agents: List[str] = []
    in_agent_block = False

    for raw_line in robots_text.splitlines():
        stripped_raw = raw_line.strip()
        # Comments should NOT reset current_agents (RFC 9309 §2.1)
        if stripped_raw.startswith("#"):
            continue

        # Truly blank lines separate agent groups (RFC 9309 §2.2)
        if not stripped_raw:
            current_agents = []
            in_agent_block = False
            continue

        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        if ":" not in line:
            continue

        field, _, val = line.partition(":")
        field = field.strip().lower()
        val   = val.strip()

        if field == "user-agent":
            if not in_agent_block:
                current_agents = []
                in_agent_block = True
            agent_key = val.lower()
            current_agents.append(agent_key)
            if agent_key not in rules:
                rules[agent_key] = {"allow": [], "disallow": [], "crawl_delay": None}

        elif field == "disallow":
            in_agent_block = False
            if val:
                for ag in current_agents:
                    if ag in rules:
                        rules[ag]["disallow"].append(val)

        elif field == "allow":
            in_agent_block = False
            if val:
                for ag in current_agents:
                    if ag in rules:
                        rules[ag]["allow"].append(val)

        elif field == "crawl-delay":
            in_agent_block = False
            try:
                delay = float(val)
                for ag in current_agents:
                    if ag in rules and rules[ag]["crawl_delay"] is None:
                        rules[ag]["crawl_delay"] = delay
            except ValueError:
                pass

    return rules


def _match_robots_pattern(pattern: str, path: str) -> bool:
    """Match a path against an RFC 9309 robots.txt pattern (supporting * and $)."""
    if not pattern:
        return False
    if "*" not in pattern and not pattern.endswith("$"):
        return path.startswith(pattern)
    escaped = re.escape(pattern)
    regex_str = "^" + escaped.replace(r"\*", ".*")
    if regex_str.endswith(r"\$"):
        regex_str = regex_str[:-2] + "$"
    return bool(re.match(regex_str, path))


def is_bot_blocked(
    rules: Dict[str, Dict[str, Any]],
    bot: str,
    path: str = "/",
) -> bool:
    bot_lower = bot.lower()

    if bot_lower in rules:
        agent_rules = rules[bot_lower]
    elif "*" in rules:
        agent_rules = rules["*"]
    else:
        return False

    if not path.startswith("/"):
        path = "/" + path

    def _best_match(directive_list: List[str]) -> str:
        best = ""
        for rule in directive_list:
            if not rule:
                continue
            if _match_robots_pattern(rule, path):
                if len(rule) > len(best):
                    best = rule
        return best

    best_disallow = _best_match(agent_rules.get("disallow", []))
    if not best_disallow:
        return False

    best_allow = _best_match(agent_rules.get("allow", []))
    if not best_allow:
        return True

    return len(best_disallow) > len(best_allow)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def check_robots_txt(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify_ssl: bool = True,
    context: Optional[AuditContext] = None,
    robots_txt: Optional[str] = None,
) -> List[Dict[str, Any]]:
    findings_out: List[Dict[str, Any]] = []
    root        = domain_root(url)
    robots_url  = f"{root}/robots.txt"

    if robots_txt is not None:
        robots_body = robots_txt
        status_code = 200
    else:
        if context is not None:
            resp = context.get_robots_txt()
        else:
            session = make_session(verify_ssl=verify_ssl)
            resp = polite_get(robots_url, HEADERS_BROWSER, timeout=timeout,
                              verify_ssl=verify_ssl, session=session)

        if resp is None:
            return findings_out
        robots_body = resp.text
        status_code = resp.status_code

    if status_code == 200 and robots_body.strip():
        rules = parse_robots_txt(robots_body)
        target_path = urlparse(url).path or "/"
        blocked_root_bots: set = set()
        restricted_subpath_bots: set = set()

        for bot in AI_BOTS:
            if is_bot_blocked(rules, bot, "/"):
                blocked_root_bots.add(bot)
            else:
                if target_path != "/" and is_bot_blocked(rules, bot, target_path):
                    restricted_subpath_bots.add(bot)
                    continue
                for check_path in ("/products", "/catalog", "/shop", "/blog"):
                    if is_bot_blocked(rules, bot, check_path):
                        restricted_subpath_bots.add(bot)
                        break

        # Split blocked bots into: major AI search bots vs fringe/data-harvesting bots
        blocked_major = {b for b in blocked_root_bots if b.lower() in MAJOR_AI_BOTS}
        blocked_fringe = blocked_root_bots - blocked_major

        # Distinguish core AI search engines from secondary/training bots
        blocked_core = {b for b in blocked_major if b.lower() in CORE_AI_SEARCH_BOTS}

        # Critical ONLY when core AI search engines are blocked at root
        if blocked_core:
            findings_out.append(finding(
                title="AI Web Crawlers Blocked in robots.txt",
                severity="critical",
                evidence=(
                    f"robots.txt at {robots_url} disallows root indexing "
                    f"for major AI search agents: {', '.join(sorted(blocked_core))}. "
                    f"These bots power ChatGPT, Perplexity, and Claude citations."
                ),
                action_summary=(
                    "Update robots.txt to explicitly allow AI search crawlers "
                    "(GPTBot, PerplexityBot, ClaudeBot, Google-Extended) to index "
                    "public product and content routes."
                ),
                action_priority="high",
                confidence=0.98,
            ))
        elif blocked_major:
            # Secondary/training bots (Applebot-Extended, Claude-Web) blocked, but core search engines allowed
            findings_out.append(finding(
                title="Secondary AI Crawlers Restricted in robots.txt",
                severity="low",
                evidence=(
                    f"robots.txt at {robots_url} permits core AI search engines (GPTBot, ClaudeBot, PerplexityBot) "
                    f"but restricts secondary or training bots: {', '.join(sorted(blocked_major))}. "
                    f"Core AI search discoverability remains functional."
                ),
                action_summary=(
                    f"Review whether access for {', '.join(sorted(blocked_major))} aligns with your brand's AI strategy."
                ),
                action_priority="low",
                confidence=0.85,
            ))
        elif blocked_fringe:
            # Fringe bots (CCBot, Bytespider, Amazonbot) blocked — lower severity
            findings_out.append(finding(
                title="Fringe Data-Harvesting Bots Blocked in robots.txt",
                severity="low",
                evidence=(
                    f"robots.txt at {robots_url} blocks fringe data-harvesting bots "
                    f"({', '.join(sorted(blocked_fringe))}) but permits major AI search engines "
                    f"(GPTBot, ClaudeBot, PerplexityBot). This is a deliberate and acceptable choice."
                ),
                action_summary=(
                    "No action required for major AI discoverability. "
                    "Review if any blocked bots are needed for your AI distribution strategy."
                ),
                action_priority="low",
                confidence=0.80,
            ))

        if restricted_subpath_bots:
            findings_out.append(finding(
                title="Core Catalog Path Disallowed in robots.txt",
                severity="medium",
                evidence=(
                    f"robots.txt at {robots_url} permits root indexing but restricts "
                    f"subpaths (/products, /catalog, /shop) for: {', '.join(sorted(restricted_subpath_bots))}."
                ),
                action_summary=(
                    "Ensure public catalog, shopping, or knowledge routes are open "
                    "to verified AI search crawlers."
                ),
                action_priority="medium",
                confidence=0.85,
            ))

        if not blocked_major and not blocked_fringe and not restricted_subpath_bots:
            pass  # All bots permitted — no finding needed

    elif resp.status_code in (401, 403):
        findings_out.append(finding(
            title="robots.txt Inaccessible (HTTP 403/401)",
            severity="high",
            evidence=(
                f"Request to {robots_url} returned HTTP {resp.status_code}. "
                "AI crawlers cannot verify crawl permissions."
            ),
            action_summary=(
                "Ensure robots.txt is publicly accessible with HTTP 200 for all web agents."
            ),
            action_priority="high",
            confidence=1.0,
        ))

    return findings_out


def check_waf_bot_blocking(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify_ssl: bool = True,
) -> List[Dict[str, Any]]:
    findings_out: List[Dict[str, Any]] = []
    session = make_session(verify_ssl=verify_ssl)
    resp    = polite_get(url, HEADERS_AIBOT, timeout=timeout,
                         verify_ssl=verify_ssl, session=session)
    if resp is not None and resp.status_code in (401, 403, 429):
        findings_out.append(finding(
            title="AI Crawler User-Agent Blocked by Server/WAF",
            severity="critical",
            evidence=(
                f"Requesting {url} with a GPTBot User-Agent returned "
                f"HTTP {resp.status_code}."
            ),
            action_summary=(
                "Configure Cloudflare, Akamai, or edge firewall rules to allow "
                "verified AI search crawlers rather than issuing an automated block."
            ),
            action_priority="high",
            confidence=0.92,
        ))
    return findings_out


def check_antibot_challenges(html_text: str) -> List[Dict[str, Any]]:
    findings_out: List[Dict[str, Any]] = []
    if not html_text:
        return findings_out

    detected = [
        provider
        for provider, patterns in ANTIBOT_SIGNATURES.items()
        if any(re.search(p, html_text, re.I) for p in patterns)
    ]

    if detected:
        findings_out.append(finding(
            title="Anti-Bot / CAPTCHA Challenge Interception Detected",
            severity="high",
            evidence=(
                f"Found interactive bot-protection signatures "
                f"({', '.join(detected)}) embedded in initial HTML payload."
            ),
            action_summary=(
                "Exempt verified AI crawler User-Agents or adopt cryptographic agent "
                "authentication to allow indexing without a manual challenge."
            ),
            action_priority="high",
            confidence=0.88,
        ))
    return findings_out


def check_csr_dependency(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify_ssl: bool = True,
    html_text: Optional[str] = None,
    context: Optional[AuditContext] = None,
) -> List[Dict[str, Any]]:
    findings_out: List[Dict[str, Any]] = []

    if html_text is None:
        if context is not None:
            resp, html_text, _ = context.get_root_page()
        else:
            session = make_session(verify_ssl=verify_ssl)
            resp = polite_get(url, HEADERS_BROWSER, timeout=timeout,
                              verify_ssl=verify_ssl, session=session)
            html_text = resp.text if resp is not None else None

        if resp is None:
            findings_out.append(finding(
                title="Website Unreachable for Crawl Test",
                severity="high",
                evidence=f"Network request to {url} failed. Site may be down or blocked.",
                action_summary="Verify the site is publicly reachable over HTTPS.",
                action_priority="high",
                confidence=0.95,
            ))
            return findings_out

        if resp.status_code >= 400:
            findings_out.append(finding(
                title="Non-200 Response on Primary Page Fetch",
                severity="high",
                evidence=f"GET {url} returned HTTP {resp.status_code}.",
                action_summary="Investigate server errors or bot-blocking rules causing non-success responses.",
                action_priority="high",
                confidence=1.0,
            ))
            return findings_out

    if not html_text:
        return findings_out

    findings_out.extend(check_antibot_challenges(html_text))

    try:
        soup = BeautifulSoup(html_text, "lxml")
    except Exception:
        soup = BeautifulSoup(html_text, "html.parser")

    scripts      = soup.find_all("script")
    script_bytes = sum(len(s.string or s.get_text() or "") for s in scripts)
    total_scripts = len(scripts)

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    body_text  = soup.get_text(separator=" ", strip=True)
    word_count = len(body_text.split())

    spa_root          = soup.select_one(SPA_ROOT_SELECTOR)
    spa_root_text_len = len(spa_root.get_text(strip=True)) if spa_root else None

    # Modern SPAs (Vite, CRA, Webpack external bundles) often have empty spa_root and minimal text (<50 words)
    has_empty_spa_root = (
        spa_root is not None
        and (spa_root_text_len or 0) < 40
    )
    is_modern_spa = has_empty_spa_root and word_count < 50
    is_heavy_inline_csr = (
        has_empty_spa_root
        and (script_bytes > 40_000 or total_scripts >= 8)
        and word_count < 200
    )
    is_likely_csr = is_modern_spa or is_heavy_inline_csr

    if is_likely_csr:
        script_info = f"{total_scripts} script tags"
        if script_bytes > 0:
            script_info += f" ({round(script_bytes / 1024, 1)} KB inline JS)"
        findings_out.append(finding(
            title="Content Hidden Behind Client-Side JavaScript (CSR)",
            severity="high",
            evidence=(
                f"Raw server-rendered HTML contains only {word_count} visible words "
                f"with {script_info}. "
                "Empty SPA root container detected. "
                "AI crawlers that do not execute JavaScript see a near-empty page."
            ),
            action_summary=(
                "Adopt Server-Side Rendering (SSR) or Static Site Generation (SSG) "
                "for key entity/product pages so facts exist in the raw HTML response."
            ),
            action_priority="high",
            confidence=0.85,
        ))

    return findings_out


def run_checks(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify_ssl: bool = True,
    context: Optional[AuditContext] = None,
) -> List[Dict[str, Any]]:
    norm_url = normalize_url(url)
    results: List[Dict[str, Any]] = []
    results.extend(check_robots_txt(norm_url, timeout=timeout, verify_ssl=verify_ssl, context=context))
    results.extend(check_waf_bot_blocking(norm_url, timeout=timeout, verify_ssl=verify_ssl))
    results.extend(check_csr_dependency(norm_url, timeout=timeout, verify_ssl=verify_ssl, context=context))
    return results


def audit_crawl_render(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify_ssl: bool = True,
    html_text: Optional[str] = None,
    context: Optional[AuditContext] = None,
) -> List[Dict[str, Any]]:
    norm_url = normalize_url(url)
    results: List[Dict[str, Any]] = []
    results.extend(check_robots_txt(norm_url, timeout=timeout, verify_ssl=verify_ssl, context=context))
    results.extend(check_waf_bot_blocking(norm_url, timeout=timeout, verify_ssl=verify_ssl))
    results.extend(check_csr_dependency(norm_url, timeout=timeout, verify_ssl=verify_ssl,
                                         html_text=html_text, context=context))
    return results


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="crawl-render-audit standalone runner")
    parser.add_argument("url_pos", nargs="?", default=None, help="Target website URL")
    parser.add_argument("--url", dest="url_opt", default=None, help="Target website URL")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Per-request timeout in seconds")
    parser.add_argument("--no-verify-ssl", dest="no_verify_ssl", action="store_true", help="Disable TLS verification")
    args = parser.parse_args()

    target_url = args.url_opt or args.url_pos
    if not target_url:
        parser.error("A target URL must be provided via positional argument or --url flag.")

    results = run_checks(target_url, timeout=args.timeout, verify_ssl=not args.no_verify_ssl)
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":  # pragma: no cover
    main()
