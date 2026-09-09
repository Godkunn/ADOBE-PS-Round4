#!/usr/bin/env python3
"""
skills/shared/utils.py

Shared utility functions for Brand AI Readiness Audit skills:
- SSRF protection & safe URL validation
- URL normalisation & domain extraction
- Connection-pooled HTTP session factory
- Non-blocking crawl politeness (fine-grained thread scheduling)
- Canonical finding() factory
- 4-Pillar weighted GEO score calculation engine
- AuditContext for single-fetch shared DOM caching across sub-skills
"""

from __future__ import annotations

import os
import sys
import time
import ipaddress
import socket
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Module-level rate-limit state (per-domain scheduling, lock released before sleep)
# ---------------------------------------------------------------------------
_DOMAIN_NEXT_ALLOWED: Dict[str, float] = {}
_DOMAIN_LOCK = threading.Lock()

#: Minimum gap between successive requests to the SAME domain (crawl politeness).
CRAWL_POLITENESS_SECONDS: float = float(os.environ.get("AUDIT_CRAWL_DELAY", "0.5"))

#: Browser headers for standard web fetches
HEADERS_BROWSER: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# URL helpers & SSRF Protection
# ---------------------------------------------------------------------------
def normalize_url(raw_url: str) -> str:
    """Strip whitespace and ensure a valid HTTP/HTTPS scheme is present."""
    raw_url = raw_url.strip()
    if not raw_url.startswith(("http://", "https://")):
        try:
            ip = ipaddress.ip_address(raw_url)
            if isinstance(ip, ipaddress.IPv6Address):
                raw_url = f"[{raw_url}]"
        except ValueError:
            pass
        raw_url = "https://" + raw_url
    return raw_url


def domain_root(url: str) -> str:
    """Return scheme + netloc (e.g. 'https://example.com') from any URL."""
    parsed = urlparse(url)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc.lstrip("/")
    return f"{scheme}://{netloc}"


def domain_of(url: str) -> str:
    """Return the bare netloc/hostname of a URL (lowercase, no port)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        parsed = urlparse(normalize_url(url))
    return (parsed.hostname or "").lower()


def current_year() -> int:
    """Return the current UTC calendar year."""
    return datetime.now(timezone.utc).year


def _is_bsd_shorthand_ip(hostname: str) -> bool:
    """
    Detect BSD shorthand / non-standard numeric IP notations (e.g. '0', '127.1', '127.0.1',
    '0177.0.0.1', '0x7f.1', raw integers).
    Standard ICANN domain names never have purely numeric TLDs or octal/hex components.
    """
    parts = hostname.split(".")
    if not (1 <= len(parts) <= 4):
        return False
    for p in parts:
        p_str = p.strip()
        if not p_str:
            return False
        if p_str.lower().startswith("0x"):
            try:
                int(p_str, 16)
            except ValueError:
                return False
        elif p_str.isdigit():
            pass
        else:
            return False
    if len(parts) < 4:
        return True
    for p in parts:
        if p.lower().startswith("0x") or (len(p) > 1 and p.startswith("0")):
            return True
    return False


def _is_prohibited_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address, allow_local: bool = False) -> Tuple[bool, str]:
    """Check if an IP address falls into loopback, private, link-local, unspecified, or reserved ranges."""
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped:
        ip_obj = ip_obj.ipv4_mapped

    if ip_obj.is_loopback:
        if allow_local:
            return False, ""
        return True, f"Loopback address '{ip_obj}' is blocked."
    if ip_obj.is_unspecified:
        return True, f"Unspecified address '{ip_obj}' is blocked."
    if ip_obj.is_link_local:
        return True, f"Link-local address '{ip_obj}' is blocked."
    if ip_obj.is_private:
        return True, f"Private/internal address '{ip_obj}' is blocked."
    if ip_obj.is_multicast or ip_obj.is_reserved:
        return True, f"Multicast/reserved address '{ip_obj}' is blocked."
    if not ip_obj.is_global:
        return True, f"Non-global/internal address '{ip_obj}' is blocked."
    return False, ""


def is_safe_target_url(raw_url: str) -> Tuple[bool, str]:
    """
    Validate target URL against Server-Side Request Forgery (SSRF).

    Rejects non-HTTP(S) schemes, private network IP ranges (RFC 1918),
    loopback addresses (127.0.0.0/8, ::1), link-local addresses (169.254.0.0/16),
    unspecified addresses (0.0.0.0, ::), BSD shorthand notation (http://0, http://127.1),
    and internal cloud metadata endpoints.
    Allows local/test addresses when AUDIT_ALLOW_LOCAL_TEST=1 or host ends in .test.
    """
    try:
        norm = normalize_url(raw_url)
        parsed = urlparse(norm)
    except Exception as exc:
        return False, f"Invalid URL syntax: {exc}"

    if parsed.scheme not in ("http", "https"):
        return False, f"Prohibited URL scheme: '{parsed.scheme}'. Only http and https are allowed."

    hostname = parsed.hostname
    if not hostname:
        return False, "Target URL lacks a valid hostname."

    # Block BSD shorthand IP notations (e.g. http://0, http://127.1, 0x7f000001)
    if _is_bsd_shorthand_ip(hostname):
        return False, f"Access to BSD shorthand / non-standard IP notation '{hostname}' is blocked."

    # Allow RFC 2606 / RFC 6761 offline test domains immediately without DNS resolution lag
    if hostname.endswith((".test", ".example", ".local", ".internal", ".invalid")):
        return True, ""

    allow_local = os.environ.get("AUDIT_ALLOW_LOCAL_TEST", "").lower() in ("1", "true", "yes")

    if hostname in ("localhost", "127.0.0.1", "::1"):
        if allow_local:
            return True, ""
        return False, f"Access to localhost/loopback address '{hostname}' is blocked for security."

    try:
        # Check if hostname is an explicit IP literal
        ip_obj = ipaddress.ip_address(hostname)
        is_proh, reason = _is_prohibited_ip(ip_obj, allow_local=allow_local)
        if is_proh:
            return False, f"Access to private/internal IP address '{hostname}' is blocked: {reason}"
        return True, ""
    except ValueError:
        # Hostname is a domain name, not an IP literal
        pass

    # Resolve hostname to IP addresses and validate all resolved IPs
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
        for family, socktype, proto, canonname, sockaddr in addr_infos:
            ip_str = sockaddr[0]
            try:
                resolved_ip = ipaddress.ip_address(ip_str)
                is_proh, reason = _is_prohibited_ip(resolved_ip, allow_local=allow_local)
                if is_proh:
                    return False, f"Target hostname '{hostname}' resolves to prohibited IP '{ip_str}': {reason}"
            except ValueError:
                continue
    except (socket.gaierror, socket.herror):
        # Hostname could not be resolved via DNS (offline, mock test domain, or non-existent)
        pass
    except Exception:
        pass

    return True, ""


# ---------------------------------------------------------------------------
# HTTP session factory
# ---------------------------------------------------------------------------
def make_session(verify_ssl: bool = True) -> requests.Session:
    """
    Build a requests.Session with connection pooling, conservative retry
    strategy, and correct TLS verification.
    """
    session = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=0.3,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
        respect_retry_after_header=True,
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(
        pool_connections=8,
        pool_maxsize=16,
        max_retries=retry,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.verify = verify_ssl
    return session


# ---------------------------------------------------------------------------
# Polite HTTP GET with non-blocking per-domain rate limiting
# ---------------------------------------------------------------------------
def polite_get(
    url: str,
    headers: Dict[str, str],
    timeout: int = 10,
    verify_ssl: bool = True,
    session: Optional[requests.Session] = None,
    max_redirects: int = 5,
) -> Optional[requests.Response]:
    """
    Perform a GET request while honouring a minimum per-domain crawl delay.
    Crucial fix: Lock is released before time.sleep(), preventing global thread blocking.
    Protects against redirect SSRF by validating every redirect hop with is_safe_target_url().
    """
    current_url = url
    req_session = session or make_session(verify_ssl=verify_ssl)
    history: List[requests.Response] = []

    for _ in range(max_redirects + 1):
        safe, _ = is_safe_target_url(current_url)
        if not safe:
            return None

        domain = domain_of(current_url)

        with _DOMAIN_LOCK:
            now = time.monotonic()
            next_allowed = _DOMAIN_NEXT_ALLOWED.get(domain, 0.0)
            if now < next_allowed:
                wait_time = next_allowed - now
                _DOMAIN_NEXT_ALLOWED[domain] = next_allowed + CRAWL_POLITENESS_SECONDS
            else:
                wait_time = 0.0
                _DOMAIN_NEXT_ALLOWED[domain] = now + CRAWL_POLITENESS_SECONDS

        if wait_time > 0:
            time.sleep(wait_time)

        try:
            resp = req_session.get(
                current_url,
                headers=headers,
                timeout=timeout,
                verify=verify_ssl,
                allow_redirects=False,
            )
        except requests.RequestException:
            return None

        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            if not location:
                resp.history = history
                return resp
            next_url = urljoin(current_url, location)
            history.append(resp)
            current_url = next_url
            continue

        resp.history = history
        return resp

    return None


# ---------------------------------------------------------------------------
# Canonical finding factory
# ---------------------------------------------------------------------------
def finding(
    title: str,
    severity: str,
    evidence: str,
    action_summary: str,
    action_priority: str,
    confidence: float = 1.0,
) -> Dict[str, Any]:
    """Construct a normalised finding dict conforming strictly to hackathon schema."""
    _SEV = {"critical", "high", "medium", "low"}
    _PRI = {"high", "medium", "low"}
    sev = severity.lower() if severity.lower() in _SEV else "medium"
    pri = action_priority.lower() if action_priority.lower() in _PRI else "medium"
    conf = round(max(0.0, min(1.0, float(confidence))), 2)

    return {
        "title": title,
        "severity": sev,
        "evidence": evidence,
        "suggested_action": {
            "summary": action_summary,
            "priority": pri,
        },
        "confidence": conf,
    }


# ---------------------------------------------------------------------------
# 4-Pillar GEO Score Calculation Engine
# ---------------------------------------------------------------------------
PILLAR_MAPPING: Dict[str, str] = {
    # Pillar 1: Crawl & Render
    "AI Web Crawlers Blocked in robots.txt":              "crawl_render",
    "robots.txt Inaccessible (HTTP 403/401)":             "crawl_render",
    "AI Crawler User-Agent Blocked by Server/WAF":        "crawl_render",
    "Anti-Bot / CAPTCHA Challenge Interception Detected": "crawl_render",
    "Content Hidden Behind Client-Side JavaScript (CSR)": "crawl_render",
    "Non-200 Response on Primary Page Fetch":             "crawl_render",
    "Website Unreachable for Crawl Test":                 "crawl_render",
    "Domain Unreachable / DNS Resolution Failure":        "crawl_render",
    "Origin Connection Timeout":                          "crawl_render",
    "TLS/SSL Certificate or Handshake Failure":           "crawl_render",
    "WAF / Anti-Bot Challenge Wall Active":               "crawl_render",
    "Aggressive Rate Limiting (HTTP 429)":                "crawl_render",
    "Origin Server Error (HTTP 5xx)":                     "crawl_render",
    "Malformed HTML / DOM Parser Corruption":             "crawl_render",
    "Unexpected System Execution Notice":                 "crawl_render",
    "Core Catalog Path Disallowed in robots.txt":         "crawl_render",
    "SSRF / Prohibited Target Host Blocked":              "crawl_render",
    "Fringe Data-Harvesting Bots Blocked in robots.txt": "crawl_render",
    "Secondary AI Crawlers Restricted in robots.txt":     "crawl_render",

    # Pillar 2: Structured Data
    "Missing Machine-Readable Structured Data (JSON-LD)":            "structured_data",
    "JSON-LD Present but Missing Key Entity Types":                  "structured_data",
    "Missing Product & Offer Schema Markup":                         "structured_data",
    "Incomplete Product Schema: Missing Price or Availability":      "structured_data",
    "Missing Organization Schema Markup":                            "structured_data",
    "Missing Entity Disambiguation (sameAs) in Organization Schema": "structured_data",
    "FAQ Content Lacks Structured FAQPage Schema":                   "structured_data",
    "Could Not Fetch Page for Structured Data Check":                "structured_data",

    # Pillar 3: Freshness & Security
    "Missing Temporal & Freshness Metadata":              "freshness_security",
    "Outdated Copyright Year in Footer":                  "freshness_security",
    "Missing Canonical URL Declaration":                  "freshness_security",
    "Missing Strict-Transport-Security (HSTS) Header":    "freshness_security",
    "Sitemap Not Found (/sitemap.xml Inaccessible)":      "freshness_security",
    "Sitemap Missing or Invalid":                         "freshness_security",
    "Sitemap URLs Lack <lastmod> Timestamps":             "freshness_security",
    "Sitemap Timestamps Appear Stale":                    "freshness_security",

    # Pillar 4: Engagement & Context
    "No H1 Heading Found":                                     "engagement",
    "Buried Direct Answer Above The Fold (High Bounce Risk)":  "engagement",
    "Missing Deep-Link Target Anchors for AI Citations":       "engagement",
    "Intrusive Modal Overlay Detected on Initial View":        "engagement",
    "Consent & Cookie Banner Friction Interception":           "engagement",
    "Heavy Third-Party Tracking & Ad Script Bloat":            "engagement",
    "Low Text-to-HTML Ratio (Excessive DOM Bloat)":            "engagement",
    "Could Not Fetch Page for Engagement Check":               "engagement",
}

PILLAR_WEIGHTS: Dict[str, float] = {
    "crawl_render":       0.40,
    "structured_data":    0.30,
    "freshness_security": 0.15,
    "engagement":         0.15,
}

_SEV_WEIGHT: Dict[str, float] = {
    "critical": 25.0,
    "high":     15.0,
    "medium":   7.0,
    "low":      3.0,
}


def get_finding_category(title: str) -> str:
    """Return the pillar category for a finding title with keyword fallback."""
    if title in PILLAR_MAPPING:
        return PILLAR_MAPPING[title]
    t = title.lower()
    if any(k in t for k in ["robot", "csr", "javascript", "waf", "dns", "timeout",
                           "tls", "ssl", "429", "5xx", "unreachable", "crawl", "captcha",
                           "ssrf", "prohibited"]):
        return "crawl_render"
    if any(k in t for k in ["json-ld", "schema", "product", "offer", "organization",
                           "sameas", "faq", "structured"]):
        return "structured_data"
    if any(k in t for k in ["freshness", "sitemap", "copyright", "canonical",
                           "hsts", "temporal", "lastmod", "modified"]):
        return "freshness_security"
    return "engagement"


def calculate_pillar_scores(findings: list) -> Dict[str, float]:
    """Calculate individual pillar health scores [10.0, 100.0]."""
    scores: Dict[str, float] = {p: 100.0 for p in PILLAR_WEIGHTS}
    for f in findings:
        cat = get_finding_category(f.get("title", ""))
        sev = str(f.get("severity", "medium")).lower()
        conf = float(f.get("confidence", 1.0))
        deduction = _SEV_WEIGHT.get(sev, 7.0) * conf
        scores[cat] = max(10.0, scores[cat] - deduction)
    return {p: round(score, 1) for p, score in scores.items()}


def calculate_geo_score(findings: list) -> int:
    """
    Calculate GEO readiness score using the weighted 4-pillar model.
    Bounded [10, 100]. Clean sites score 100.
    """
    pillar_scores = calculate_pillar_scores(findings)
    weighted = sum(pillar_scores[p] * w for p, w in PILLAR_WEIGHTS.items())
    return max(10, min(100, int(round(weighted))))


# ---------------------------------------------------------------------------
# Shared Audit Context (Eliminates redundant network round-trips)
# ---------------------------------------------------------------------------
class AuditContext:
    """
    Shared context created by the orchestrator for a single target URL.
    Fetches the root page and robots.txt ONCE and caches the response and DOM,
    drastically reducing audit latency and rate-limit friction.
    """
    def __init__(self, target_url: str, timeout: int = 10, verify_ssl: bool = True):
        self.url = normalize_url(target_url)
        self.root_url = domain_root(self.url)
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.session = make_session(verify_ssl=verify_ssl)

        self._root_resp: Optional[requests.Response] = None
        self._root_html: Optional[str] = None
        self._root_soup: Optional[Any] = None
        self._robots_resp: Optional[requests.Response] = None
        self._lock = threading.Lock()

    def get_root_page(self) -> Tuple[Optional[requests.Response], Optional[str], Optional[Any]]:
        """Fetch and cache root HTML response and parsed DOM."""
        with self._lock:
            if self._root_resp is None:
                self._root_resp = polite_get(
                    self.url,
                    headers=HEADERS_BROWSER,
                    timeout=self.timeout,
                    verify_ssl=self.verify_ssl,
                    session=self.session,
                )
                if self._root_resp is not None and self._root_resp.status_code < 400:
                    self._root_html = self._root_resp.text
                    if BeautifulSoup is not None and self._root_html:
                        try:
                            self._root_soup = BeautifulSoup(self._root_html, "lxml")
                        except Exception:
                            self._root_soup = BeautifulSoup(self._root_html, "html.parser")
            return self._root_resp, self._root_html, self._root_soup

    def get_robots_txt(self) -> Optional[requests.Response]:
        """Fetch and cache robots.txt."""
        with self._lock:
            if self._robots_resp is None:
                robots_url = f"{self.root_url}/robots.txt"
                self._robots_resp = polite_get(
                    robots_url,
                    headers=HEADERS_BROWSER,
                    timeout=self.timeout,
                    verify_ssl=self.verify_ssl,
                    session=self.session,
                )
            return self._robots_resp
