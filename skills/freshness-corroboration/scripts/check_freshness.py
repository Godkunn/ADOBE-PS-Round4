#!/usr/bin/env python3
"""
freshness-corroboration / check_freshness.py

Detects stale-fact signals:
  - Missing temporal metadata (OpenGraph, Schema.org, HTTP headers).
  - Absent/stale sitemap lastmod entries.
  - Outdated copyright year in footer.
  - Missing canonical <link> declaration.
  - Missing Strict-Transport-Security (HSTS) header.

Production Refinements:
  - Dual CLI argument support: positional <URL> and --url <URL> (PROJECT.md §3.3).
  - Shared AuditContext support to eliminate duplicate fetches.
  - Intent-aware temporal check: avoids false positives on corporate homepages.
  - Tightened copyright regex to prevent false positives on SKUs/phone numbers.
  - Confidence scores on every finding.

Read-only: GET requests only, never modifies the target site.
"""

from __future__ import annotations

import os
import sys
import json
import re
import argparse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

_SHARED_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "shared")
)
if _SHARED_DIR not in sys.path:
    sys.path.insert(0, _SHARED_DIR)
from utils import (
    normalize_url, domain_root, polite_get, make_session,
    finding, current_year, AuditContext, HEADERS_BROWSER,
    is_safe_target_url,
)

try:
    from bs4 import BeautifulSoup
except ImportError as exc:  # pragma: no cover
    raise ImportError("beautifulsoup4 is required: pip install beautifulsoup4") from exc

DEFAULT_TIMEOUT = 10


def _discover_sitemap_urls(
    root_url: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify_ssl: bool = True,
    session: Optional[requests.Session] = None,
    context: Optional[AuditContext] = None,
) -> List[str]:
    candidates: List[str] = []

    if context is not None:
        resp = context.get_robots_txt()
    else:
        robots_url = f"{root_url}/robots.txt"
        resp = polite_get(robots_url, HEADERS_BROWSER, timeout=timeout,
                          verify_ssl=verify_ssl, session=session)

    if resp is not None and resp.status_code == 200:
        for line in resp.text.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("sitemap:"):
                sitemap_val = stripped.split(":", 1)[1].strip()
                sitemap_val = sitemap_val.split("#", 1)[0].strip()
                if not sitemap_val:
                    continue
                if not sitemap_val.startswith(("http://", "https://")):
                    from urllib.parse import urljoin
                    sitemap_val = urljoin(root_url, sitemap_val)
                safe, _ = is_safe_target_url(sitemap_val)
                if safe and sitemap_val not in candidates:
                    candidates.append(sitemap_val)

    if not candidates:
        candidates = [
            f"{root_url}/sitemap.xml",
            f"{root_url}/sitemap_index.xml",
            f"{root_url}/sitemap.xml.gz",
        ]

    return candidates


def check_temporal_metadata(
    url: str,
    soup: BeautifulSoup,
    resp_headers: Dict[str, str],
) -> List[Dict[str, Any]]:
    findings_out: List[Dict[str, Any]] = []
    has_timestamp = False

    # Check if page signals that it is an article/blog
    og_type_tag = soup.find("meta", attrs={"property": "og:type"})
    is_article = og_type_tag and "article" in str(og_type_tag.get("content", "")).lower()

    # 1. OpenGraph / meta date tags
    meta_date_names = [
        "article:modified_time", "og:updated_time", "article:published_time",
        "last-modified", "date", "pubdate", "sailthru.date", "parsely-pub-date",
    ]
    for name in meta_date_names:
        tag = (
            soup.find("meta", attrs={"property": name})
            or soup.find("meta", attrs={"name": name})
        )
        if tag and tag.get("content"):
            has_timestamp = True
            break

    # 2. <time datetime="..."> element
    if not has_timestamp:
        time_tag = soup.find("time")
        if time_tag and time_tag.get("datetime"):
            has_timestamp = True

    # 3. Schema.org dateModified / datePublished in JSON-LD
    if not has_timestamp:
        for tag in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
            raw = tag.string or tag.get_text() or ""
            if "dateModified" in raw or "datePublished" in raw:
                has_timestamp = True
                break

    # 4. HTTP Last-Modified response header
    if not has_timestamp:
        h_lower = {k.lower(): v for k, v in resp_headers.items()}
        if "last-modified" in h_lower:
            has_timestamp = True

    # Intent-aware: on articles require timestamp; on generic pages require only if no other temporal signals exist
    if not has_timestamp and is_article:
        findings_out.append(finding(
            title="Missing Temporal & Freshness Metadata",
            severity="medium",
            evidence=(
                f"Article page {url} exposes no article:modified_time meta tag, "
                "Last-Modified HTTP header, or dateModified schema field. "
                "AI search engines cannot verify content recency."
            ),
            action_summary=(
                "Publish machine-readable ISO-8601 timestamps in OpenGraph "
                "(article:modified_time) and Schema.org (dateModified) metadata."
            ),
            action_priority="medium",
            confidence=0.95,
        ))
    elif not has_timestamp and not is_article:
        # For non-article root pages, emit informational finding only if neither headers nor schema contain dates
        path = urlparse(url).path
        if path not in ("", "/"):
            findings_out.append(finding(
                title="Missing Temporal & Freshness Metadata",
                severity="low",
                evidence=(
                    f"Page at {url} exposes no machine-readable modified timestamp. "
                    "AI systems rely on temporal metadata to assess information recency."
                ),
                action_summary=(
                    "Add ISO-8601 dateModified metadata or broadcast Last-Modified HTTP headers."
                ),
                action_priority="low",
                confidence=0.80,
            ))

    # -------------------------------------------------------------------------
    # Copyright year freshness
    # -------------------------------------------------------------------------
    footer = soup.find("footer")
    footer_text = (
        footer.get_text(" ", strip=True)
        if footer
        else soup.get_text(" ", strip=True)[-3000:]
    )

    year_matches = re.findall(
        r"(?:©|copyright|\(c\))\s*(?:\d{4}\s*[-–—]\s*)?(\d{4})",
        footer_text,
        re.IGNORECASE,
    )
    if not year_matches:
        context_match = re.search(
            r"(?:©|copyright|\(c\))\s+(.{0,30})",
            footer_text,
            re.IGNORECASE,
        )
        if context_match:
            year_matches = re.findall(r"(20\d{2})", context_match.group(1))

    if year_matches:
        latest_year = max(int(y) for y in year_matches)
        cur         = current_year()
        if 1990 <= latest_year < (cur - 1):
            findings_out.append(finding(
                title="Outdated Copyright Year in Footer",
                severity="low",
                evidence=(
                    f"Footer copyright year is {latest_year} "
                    f"({cur - latest_year} year(s) behind current year {cur}). "
                    "AI models treat stale copyright as a proxy for neglected brand assets."
                ),
                action_summary=(
                    f"Update footer copyright year to dynamic {cur} across "
                    "global page templates."
                ),
                action_priority="low",
                confidence=0.80,
            ))

    # -------------------------------------------------------------------------
    # Canonical link
    # -------------------------------------------------------------------------
    canonical_tag = soup.find("link", rel=re.compile(r"^canonical$", re.I))
    if not canonical_tag or not canonical_tag.get("href"):
        findings_out.append(finding(
            title="Missing Canonical URL Declaration",
            severity="medium",
            evidence=(
                "Page does not declare a <link rel='canonical'> tag. "
                "Inconsistent URLs may cause conflicting knowledge citations across AI engines."
            ),
            action_summary=(
                "Add a self-referential <link rel='canonical' href='https://...'> "
                "in <head> to establish a single-source-of-truth URL."
            ),
            action_priority="medium",
            confidence=0.97,
        ))

    return findings_out


def check_security_transport_health(
    url: str,
    resp_headers: Dict[str, str],
) -> List[Dict[str, Any]]:
    findings_out: List[Dict[str, Any]] = []
    if not resp_headers or not url.startswith("https://"):
        return findings_out

    h_lower = {k.lower(): v for k, v in resp_headers.items()}
    if "strict-transport-security" not in h_lower:
        findings_out.append(finding(
            title="Missing Strict-Transport-Security (HSTS) Header",
            severity="medium",
            evidence=(
                "Target HTTPS origin does not broadcast a Strict-Transport-Security header. "
                "Autonomous web scrapers flag non-HSTS origins as lower transport trust."
            ),
            action_summary=(
                "Configure web server or CDN to send "
                "'Strict-Transport-Security: max-age=31536000; includeSubDomains' "
                "on all HTTPS endpoints."
            ),
            action_priority="low",
            confidence=1.0,
        ))
    return findings_out


def _parse_date(val: str) -> Optional[datetime]:
    """Parse ISO-8601, RFC 2822 / HTTP, or standard date formats into UTC datetime."""
    s = val.strip()
    # 1. ISO-8601
    try:
        cleaned = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    # 2. RFC 2822 / RFC 822 / HTTP format
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    # 3. Common standard date strings
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%Y.%m.%d", "%B %d, %Y", "%b %d, %Y", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def check_sitemap(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify_ssl: bool = True,
    session: Optional[requests.Session] = None,
    context: Optional[AuditContext] = None,
) -> List[Dict[str, Any]]:
    findings_out: List[Dict[str, Any]] = []
    root      = domain_root(url)
    req_sess  = session or make_session(verify_ssl=verify_ssl)

    candidates = _discover_sitemap_urls(root, timeout=timeout,
                                        verify_ssl=verify_ssl, session=req_sess, context=context)

    sitemap_resp  = None
    sitemap_text  = ""
    sitemap_url   = None
    for candidate in candidates:
        safe, _ = is_safe_target_url(candidate)
        if not safe:
            continue
        r = polite_get(candidate, HEADERS_BROWSER, timeout=timeout,
                       verify_ssl=verify_ssl, session=req_sess)
        if r is not None and r.status_code == 200:
            text_content = ""
            if r.content.startswith(b"\x1f\x8b") or candidate.endswith(".gz"):
                try:
                    import gzip
                    text_content = gzip.decompress(r.content).decode("utf-8", errors="replace")
                except Exception:
                    text_content = r.text or r.content.decode("utf-8", errors="replace")
            else:
                text_content = r.text

            is_valid = (
                "<urlset" in text_content.lower()
                or "<sitemapindex" in text_content.lower()
            )
            if is_valid:
                sitemap_resp = r
                sitemap_text = text_content
                sitemap_url  = candidate
                break

    if sitemap_resp is None or sitemap_url is None:
        findings_out.append(finding(
            title="Sitemap Not Found (/sitemap.xml Inaccessible)",
            severity="medium",
            evidence=(
                f"Could not locate a valid XML sitemap at {root}/sitemap.xml, "
                f"{root}/sitemap_index.xml, or via robots.txt Sitemap: directives. "
                "Search bots cannot systematically discover refreshed URLs."
            ),
            action_summary=(
                "Publish an XML sitemap at /sitemap.xml and reference it "
                "within robots.txt as 'Sitemap: https://.../sitemap.xml'."
            ),
            action_priority="medium",
            confidence=0.90,
        ))
        return findings_out

    lastmods = re.findall(
        r"<lastmod>([^<]+)</lastmod>", sitemap_text, re.IGNORECASE
    )
    if not lastmods:
        findings_out.append(finding(
            title="Sitemap URLs Lack <lastmod> Timestamps",
            severity="medium",
            evidence=(
                f"{sitemap_url} contains no <lastmod> entries, so crawlers "
                "cannot judge which pages changed recently."
            ),
            action_summary=(
                "Add accurate ISO-8601 <lastmod> values to sitemap entries, "
                "updated whenever page content changes."
            ),
            action_priority="medium",
            confidence=0.97,
        ))
        return findings_out

    now           = datetime.now(timezone.utc)
    sample        = lastmods[:50]
    parsed_count  = 0
    stale_count   = 0

    for lm in sample:
        dt = _parse_date(lm)
        if dt is not None:
            parsed_count += 1
            if (now - dt).days > 365:
                stale_count += 1

    if parsed_count > 0 and stale_count == parsed_count:
        findings_out.append(finding(
            title="Sitemap Timestamps Appear Stale",
            severity="medium",
            evidence=(
                f"All {parsed_count} sampled <lastmod> entries in {sitemap_url} "
                "are older than 12 months."
            ),
            action_summary=(
                "Regenerate sitemap lastmod values whenever content actually "
                "changes to signal freshness to AI crawlers."
            ),
            action_priority="low",
            confidence=0.88,
        ))

    return findings_out


def run_checks(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify_ssl: bool = True,
    context: Optional[AuditContext] = None,
) -> List[Dict[str, Any]]:
    norm_url    = normalize_url(url)
    findings_out: List[Dict[str, Any]] = []

    if context is not None:
        resp, html_text, soup = context.get_root_page()
    else:
        session     = make_session(verify_ssl=verify_ssl)
        resp = polite_get(norm_url, HEADERS_BROWSER, timeout=timeout,
                          verify_ssl=verify_ssl, session=session)
        html_text = resp.text if resp is not None else None
        soup = None

    if resp is not None and resp.status_code < 400:
        if soup is None and html_text:
            soup = BeautifulSoup(html_text, "html.parser")
        if soup is not None:
            resp_headers = dict(resp.headers)
            findings_out.extend(check_temporal_metadata(norm_url, soup, resp_headers))
            findings_out.extend(check_security_transport_health(norm_url, resp_headers))

    findings_out.extend(check_sitemap(norm_url, timeout=timeout,
                                      verify_ssl=verify_ssl, context=context))
    return findings_out


def audit_freshness(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify_ssl: bool = True,
    html_text: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    context: Optional[AuditContext] = None,
) -> List[Dict[str, Any]]:
    norm_url    = normalize_url(url)
    findings_out: List[Dict[str, Any]] = []

    if html_text:
        soup   = BeautifulSoup(html_text, "html.parser")
        h_dict = headers or {}
        findings_out.extend(check_temporal_metadata(norm_url, soup, h_dict))
        findings_out.extend(check_security_transport_health(norm_url, h_dict))
        findings_out.extend(check_sitemap(norm_url, timeout=timeout,
                                          verify_ssl=verify_ssl, context=context))
        return findings_out

    return run_checks(norm_url, timeout=timeout, verify_ssl=verify_ssl, context=context)


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="freshness-corroboration standalone runner")
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
