#!/usr/bin/env python3
"""
engagement-bounce-audit / check_engagement.py

Audits whether a landing page retains visitors arriving from AI-generated summaries:
  - Direct-answer proximity (H1 + concise summary paragraph above the fold).
  - Deep-link anchor IDs on major sections for AI citation precision.
  - Intrusive modal / popup overlays on initial load.
  - Consent/cookie banner friction.
  - Third-party tracker/ad script density.
  - Text-to-HTML ratio (excessive DOM bloat).

Production Refinements:
  - Dual CLI argument support: positional <URL> and --url <URL> (PROJECT.md §3.3).
  - Shared AuditContext support to eliminate duplicate fetches.
  - Robust direct-answer detection: traverses sibling blocks and semantic ancestors.
  - Single-parse text ratio calculation.
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

import requests

_SHARED_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "shared")
)
if _SHARED_DIR not in sys.path:
    sys.path.insert(0, _SHARED_DIR)
from utils import (
    normalize_url, polite_get, make_session, finding,
    AuditContext, HEADERS_BROWSER,
)

try:
    from bs4 import BeautifulSoup
except ImportError as exc:  # pragma: no cover
    raise ImportError("beautifulsoup4 is required: pip install beautifulsoup4") from exc

DEFAULT_TIMEOUT = 10

MODAL_PATTERN = re.compile(
    r"(modal|popup|newsletter[-_]?signup|overlay|lightbox"
    r"|subscribe[-_]?dialog|intercom[-_]?frame)",
    re.IGNORECASE,
)

TRACKER_SIGNATURES: Dict[str, List[str]] = {
    "Google Tag Manager / Analytics": [
        r"googletagmanager\.com", r"google-analytics\.com", r"gtag\(",
    ],
    "Meta / Facebook Pixel": [
        r"connect\.facebook\.net", r"fbq\(",
    ],
    "Hotjar / Session Recording": [
        r"static\.hotjar\.com", r"hj\(",
    ],
    "Ad Retargeting / Widgets": [
        r"criteo\.net", r"outbrain\.com", r"taboola\.com", r"doubleclick\.net",
    ],
    "TikTok Pixel": [
        r"analytics\.tiktok\.com",
    ],
}

COOKIE_WALL_SIGNATURES: List[str] = [
    r"onetrust", r"cookiebot", r"didomi", r"usercentrics",
    r"cookie-law-info", r"consent-banner",
]


# ---------------------------------------------------------------------------
# Check 1: Direct answer above the fold
# ---------------------------------------------------------------------------
def check_direct_answer(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    findings_out: List[Dict[str, Any]] = []
    h1 = soup.find("h1")

    if not h1:
        findings_out.append(finding(
            title="No H1 Heading Found",
            severity="medium",
            evidence=(
                "Page has no <h1> element, making it hard for both users and AI "
                "assistants to anchor the page's primary topic context."
            ),
            action_summary=(
                "Add a single, clear <h1> communicating the core subject at the top "
                "of the content area."
            ),
            action_priority="medium",
            confidence=1.0,
        ))
        return findings_out

    summary_found = False

    # 1. Look for candidate paragraph inside h1's parent/ancestors (strictly following h1)
    candidate_paragraphs: List[Any] = []
    following_p_tags = set(h1.find_all_next("p"))

    curr = h1.parent
    for _ in range(4):
        if not curr or curr.name in ("body", "html"):
            break
        for p in curr.find_all("p"):
            if p in following_p_tags and p not in candidate_paragraphs:
                candidate_paragraphs.append(p)
        if candidate_paragraphs:
            break
        curr = curr.parent

    # 2. If not inside ancestors, check following siblings of h1 and its container wrappers (e.g. <header>)
    if not candidate_paragraphs:
        elements_to_check = [h1]
        curr = h1.parent
        while curr and curr.name not in ("body", "html") and len(elements_to_check) < 4:
            elements_to_check.append(curr)
            if curr.name in ("header", "section", "main", "article"):
                break
            curr = curr.parent

        for elem in elements_to_check:
            for sib in elem.next_siblings:
                if hasattr(sib, "name"):
                    if sib.name == "p":
                        if sib in following_p_tags and sib not in candidate_paragraphs:
                            candidate_paragraphs.append(sib)
                    elif hasattr(sib, "find_all"):
                        for p in sib.find_all("p"):
                            if p in following_p_tags and p not in candidate_paragraphs:
                                candidate_paragraphs.append(p)
                if len(candidate_paragraphs) >= 5:
                    break
            if candidate_paragraphs:
                break

    for p in candidate_paragraphs[:5]:
        words = p.get_text(strip=True).split()
        if 8 <= len(words) <= 120:
            summary_found = True
            break

    if not summary_found:
        findings_out.append(finding(
            title="Buried Direct Answer Above The Fold (High Bounce Risk)",
            severity="medium",
            evidence=(
                "No concise (8-120 word) paragraph follows the <h1> in the hero area. "
                "AI-referred visitors must hunt for the key answer and risk bouncing."
            ),
            action_summary=(
                "Place a concise 2-3 sentence direct-answer summary immediately below "
                "the H1 heading before hero carousels or large spacers."
            ),
            action_priority="medium",
            confidence=0.78,
        ))

    return findings_out


# ---------------------------------------------------------------------------
# Check 2: Deep-link anchor IDs
# ---------------------------------------------------------------------------
def check_deep_link_anchors(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    findings_out: List[Dict[str, Any]] = []
    sections = soup.find_all(["section", "article", "h2", "h3"])

    if len(sections) >= 3:
        def _has_anchor(elem: Any) -> bool:
            if elem.get("id"):
                return True
            nested_id = elem.find(attrs={"id": True})
            if nested_id and nested_id.get("id"):
                return True
            nested_name = elem.find("a", attrs={"name": True})
            if nested_name and nested_name.get("name"):
                return True
            return False

        anchored = [s for s in sections if _has_anchor(s)]
        ratio    = len(anchored) / len(sections)

        if ratio < 0.35:
            findings_out.append(finding(
                title="Missing Deep-Link Target Anchors for AI Citations",
                severity="medium",
                evidence=(
                    f"Only {len(anchored)} out of {len(sections)} major sections/headings "
                    f"contain HTML 'id' attributes ({round(ratio * 100)}%). "
                    "AI search assistants cannot deep-link users directly to cited answers."
                ),
                action_summary=(
                    "Assign semantic HTML 'id' attributes (e.g. <h2 id='pricing'>, "
                    "<section id='specs'>) to enable precision deep-anchor citations "
                    "by AI models."
                ),
                action_priority="medium",
                confidence=0.85,
            ))

    return findings_out


# ---------------------------------------------------------------------------
# Check 3: Intrusive modal overlays
# ---------------------------------------------------------------------------
def check_modal_noise(
    raw_html: str,
    soup: BeautifulSoup,
) -> List[Dict[str, Any]]:
    findings_out: List[Dict[str, Any]] = []
    unique_modals: List[str] = []
    seen: set = set()
    matched_elements: set = set()

    for tag in soup.find_all(True):
        if any(p in matched_elements for p in tag.parents):
            continue
        raw_cls = tag.get("class", [])
        cls_val = " ".join(raw_cls) if isinstance(raw_cls, list) else str(raw_cls or "")
        id_val = str(tag.get("id") or "")
        if MODAL_PATTERN.search(cls_val) or MODAL_PATTERN.search(id_val):
            matched_elements.add(tag)
            label = id_val or cls_val
            if label and label not in seen:
                seen.add(label)
                unique_modals.append(label)

    if unique_modals:
        labels = unique_modals[:2]
        findings_out.append(finding(
            title="Intrusive Modal Overlay Detected on Initial View",
            severity="medium",
            evidence=(
                f"Detected full-screen popup/modal elements ({labels}) that may "
                "intercept visitors immediately upon arrival from AI search summaries."
            ),
            action_summary=(
                "Suppress disruptive popups for users arriving from AI search referrers, "
                "or defer modal appearance until substantial scroll depth."
            ),
            action_priority="medium",
            confidence=0.72,
        ))

    return findings_out


# ---------------------------------------------------------------------------
# Check 4: Cookie / consent wall + tracker density
# ---------------------------------------------------------------------------
def check_cookie_and_tracker_friction(raw_html: str) -> List[Dict[str, Any]]:
    findings_out: List[Dict[str, Any]] = []
    if not raw_html:
        return findings_out

    if any(re.search(sig, raw_html, re.I) for sig in COOKIE_WALL_SIGNATURES):
        findings_out.append(finding(
            title="Consent & Cookie Banner Friction Interception",
            severity="low",
            evidence=(
                "Detected aggressive consent management or cookie-wall banner markup "
                "that may freeze interaction for first-time AI-referred visitors."
            ),
            action_summary=(
                "Adopt non-blocking, asynchronous banner styling that keeps primary "
                "content readable above the fold without requiring a consent action first."
            ),
            action_priority="low",
            confidence=0.82,
        ))

    detected_trackers = [
        name
        for name, patterns in TRACKER_SIGNATURES.items()
        if any(re.search(p, raw_html, re.I) for p in patterns)
    ]

    if len(detected_trackers) >= 3:
        findings_out.append(finding(
            title="Heavy Third-Party Tracking & Ad Script Bloat",
            severity="low",
            evidence=(
                f"Detected {len(detected_trackers)} distinct tracking/ad networks "
                f"({', '.join(detected_trackers)}). Excessive third-party scripts "
                "delay First Contentful Paint and increase bounce rates."
            ),
            action_summary=(
                "Audit third-party marketing tags, defer non-critical analytics "
                "scripts, and use server-side tag management to improve page load speed."
            ),
            action_priority="low",
            confidence=0.90,
        ))

    return findings_out


# ---------------------------------------------------------------------------
# Check 5: Text-to-HTML ratio
# ---------------------------------------------------------------------------
def check_text_ratio(
    raw_html: str,
    soup: BeautifulSoup,
) -> List[Dict[str, Any]]:
    findings_out: List[Dict[str, Any]] = []
    if not raw_html or len(raw_html) < 15_000:
        return findings_out

    clean_soup = BeautifulSoup(raw_html, "html.parser")
    for tag in clean_soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        tag.decompose()

    clean_text = clean_soup.get_text(separator=" ", strip=True)
    ratio      = (len(clean_text) / len(raw_html)) * 100

    if ratio < 6.0:
        findings_out.append(finding(
            title="Low Text-to-HTML Ratio (Excessive DOM Bloat)",
            severity="low",
            evidence=(
                f"Visible body text is {round(ratio, 2)}% of the HTML payload "
                f"({len(clean_text)} text chars vs {len(raw_html)} HTML chars). "
                "Excessive markup impairs AI token-ingestion efficiency."
            ),
            action_summary=(
                "Minify markup, externalise inline CSS/JS, and eliminate unnecessary "
                "nested wrapper divs to improve content density."
            ),
            action_priority="low",
            confidence=0.88,
        ))

    return findings_out


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
def run_checks(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify_ssl: bool = True,
    context: Optional[AuditContext] = None,
) -> List[Dict[str, Any]]:
    norm_url = normalize_url(url)
    findings_out: List[Dict[str, Any]] = []

    if context is not None:
        resp, raw_html, soup = context.get_root_page()
    else:
        session = make_session(verify_ssl=verify_ssl)
        resp = polite_get(norm_url, HEADERS_BROWSER, timeout=timeout,
                          verify_ssl=verify_ssl, session=session)
        raw_html = resp.text if resp is not None else None
        soup = None

    if resp is None:
        findings_out.append(finding(
            title="Could Not Fetch Page for Engagement Check",
            severity="medium",
            evidence=f"Network request to {norm_url} failed or timed out.",
            action_summary="Ensure the page is publicly reachable over HTTPS.",
            action_priority="medium",
            confidence=1.0,
        ))
        return findings_out

    if resp.status_code >= 400:
        return findings_out

    if soup is None and raw_html:
        soup = BeautifulSoup(raw_html, "html.parser")

    if not soup or not raw_html:
        return findings_out

    findings_out.extend(check_direct_answer(soup))
    findings_out.extend(check_deep_link_anchors(soup))
    findings_out.extend(check_modal_noise(raw_html, soup))
    findings_out.extend(check_cookie_and_tracker_friction(raw_html))
    findings_out.extend(check_text_ratio(raw_html, soup))

    return findings_out


def audit_engagement(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify_ssl: bool = True,
    html_text: Optional[str] = None,
    context: Optional[AuditContext] = None,
) -> List[Dict[str, Any]]:
    norm_url = normalize_url(url)
    if html_text:
        soup = BeautifulSoup(html_text, "html.parser")
        result: List[Dict[str, Any]] = []
        result.extend(check_direct_answer(soup))
        result.extend(check_deep_link_anchors(soup))
        result.extend(check_modal_noise(html_text, soup))
        result.extend(check_cookie_and_tracker_friction(html_text))
        result.extend(check_text_ratio(html_text, soup))
        return result
    return run_checks(norm_url, timeout=timeout, verify_ssl=verify_ssl, context=context)


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="engagement-bounce-audit standalone runner")
    parser.add_argument("url_pos", nargs="?", default=None, help="Target website URL")
    parser.add_argument("--url", dest="url_opt", default=None, help="Target website URL")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--no-verify-ssl", dest="no_verify_ssl", action="store_true")
    args = parser.parse_args()

    target_url = args.url_opt or args.url_pos
    if not target_url:
        parser.error("A target URL must be provided via positional argument or --url flag.")

    results = run_checks(target_url, timeout=args.timeout, verify_ssl=not args.no_verify_ssl)
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":  # pragma: no cover
    main()
