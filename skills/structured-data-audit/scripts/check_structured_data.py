#!/usr/bin/env python3
"""
structured-data-audit / check_structured_data.py

Validates presence and completeness of Schema.org JSON-LD structured data
(Product, Offer, Organization, FAQPage, Article, sameAs) that AI retrieval
systems rely on to extract unambiguous facts.

Production Refinements:
  - Dual CLI argument support: positional <URL> and --url <URL> (PROJECT.md §3.3).
  - Shared AuditContext support for zero-redundancy page fetches.
  - FAQ heading detection using .get_text() (handles nested inline elements).
  - Consistent JSON-LD and entity validation.
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

RELEVANT_TYPES = frozenset({
    "Product", "Organization", "Corporation", "Brand",
    "FAQPage", "Article", "NewsArticle", "BlogPosting",
    "WebSite", "BreadcrumbList", "ItemList",
})


def _get_parser() -> str:
    try:
        import lxml  # noqa: F401
        return "lxml"
    except ImportError:
        return "html.parser"


_PARSER = _get_parser()


# ---------------------------------------------------------------------------
# JSON-LD extraction
# ---------------------------------------------------------------------------
def extract_json_ld_blocks(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """Extract and flatten all JSON-LD objects from <script type='application/ld+json'> tags."""
    blocks: List[Dict[str, Any]] = []
    for tag in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = tag.string or tag.get_text()
        if not raw or not raw.strip():
            continue
        try:
            data = json.loads(raw.strip())
        except Exception:
            continue

        if isinstance(data, list):
            blocks.extend(d for d in data if isinstance(d, dict))
        elif isinstance(data, dict):
            if isinstance(data.get("@graph"), list):
                blocks.extend(d for d in data["@graph"] if isinstance(d, dict))
            else:
                blocks.append(data)

    return blocks


def get_types(obj: Dict[str, Any]) -> List[str]:
    t = obj.get("@type", [])
    if isinstance(t, str):
        return [t]
    if isinstance(t, list):
        return [str(x) for x in t]
    return []


def has_type(obj: Dict[str, Any], type_name: str) -> bool:
    return type_name.lower() in [t.lower() for t in get_types(obj)]


# ---------------------------------------------------------------------------
# Check: Product schema
# ---------------------------------------------------------------------------
def check_product_schema(
    blocks: List[Dict[str, Any]],
    soup: BeautifulSoup,
) -> List[Dict[str, Any]]:
    findings_out: List[Dict[str, Any]] = []
    product_blocks = [b for b in blocks if has_type(b, "Product")]

    page_text_lower = soup.get_text().lower()
    buy_signals = [
        "add to cart", "buy now", "price:", "sku:",
        "in stock", "out of stock", "checkout", "shipping",
    ]
    buy_signal_count = sum(1 for kw in buy_signals if kw in page_text_lower)
    is_likely_product_page = buy_signal_count >= 2

    if is_likely_product_page and not product_blocks:
        findings_out.append(finding(
            title="Missing Product & Offer Schema Markup",
            severity="high",
            evidence=(
                f"Page exhibits {buy_signal_count} commercial product signals "
                "(buy/pricing keywords) but lacks Schema.org 'Product' or 'Offer' markup."
            ),
            action_summary=(
                "Implement Schema.org 'Product' and 'Offer' JSON-LD specifying "
                "name, price, priceCurrency, SKU, and availability."
            ),
            action_priority="high",
            confidence=0.88,
        ))
        return findings_out

    for block in product_blocks:
        base_missing = [f for f in ("name", "image", "description") if not block.get(f)]

        offers_raw = block.get("offers")
        if isinstance(offers_raw, list):
            offers = next(
                (o for o in offers_raw if isinstance(o, dict) and any(k in o for k in ("price", "lowPrice", "highPrice"))),
                offers_raw[0] if offers_raw and isinstance(offers_raw[0], dict) else {}
            )
        elif isinstance(offers_raw, dict):
            offers = offers_raw
        else:
            offers = {}

        offer_missing: List[str] = []
        is_aggregate = (
            offers.get("@type") == "AggregateOffer"
            or "lowPrice" in offers
            or "highPrice" in offers
        )

        if is_aggregate:
            has_low = "lowPrice" in offers and offers["lowPrice"] is not None and str(offers["lowPrice"]).strip() != ""
            has_high = "highPrice" in offers and offers["highPrice"] is not None and str(offers["highPrice"]).strip() != ""
            has_price = "price" in offers and offers["price"] is not None and str(offers["price"]).strip() != ""
            if not (has_low or has_high or has_price):
                offer_missing.append("lowPrice/price")
        else:
            has_price = (
                ("price" in offers and offers["price"] is not None and str(offers["price"]).strip() != "")
                or ("Price" in offers and offers["Price"] is not None and str(offers["Price"]).strip() != "")
            )
            if not has_price:
                offer_missing.append("price")

        has_currency = (
            ("priceCurrency" in offers and offers["priceCurrency"] is not None and str(offers["priceCurrency"]).strip() != "")
            or ("pricecurrency" in offers and offers["pricecurrency"] is not None and str(offers["pricecurrency"]).strip() != "")
        )
        if not has_currency:
            offer_missing.append("priceCurrency")

        has_avail = (
            ("availability" in offers and offers["availability"] is not None and str(offers["availability"]).strip() != "")
            or ("Availability" in offers and offers["Availability"] is not None and str(offers["Availability"]).strip() != "")
        )
        if not is_aggregate and not has_avail:
            offer_missing.append("availability")

        if not base_missing and not offer_missing and offers:
            continue

        missing_total: List[str] = []
        if not offers:
            missing_total.append("offers (price, priceCurrency, availability)")
        else:
            missing_total.extend(offer_missing)
        missing_total.extend(base_missing)

        severity = "high" if not offers else "medium"
        findings_out.append(finding(
            title="Incomplete Product Schema: Missing Price or Availability",
            severity=severity,
            evidence=(
                f"Product JSON-LD is missing mandatory field(s): "
                f"{', '.join(missing_total) or 'none'}."
            ),
            action_summary=(
                "Populate all required Product schema fields (name, image, description) "
                "and nested Offer fields (price, priceCurrency, availability)."
            ),
            action_priority="high" if severity == "high" else "medium",
            confidence=0.92,
        ))

    return findings_out


# ---------------------------------------------------------------------------
# Check: Organization schema
# ---------------------------------------------------------------------------
def check_organization_schema(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    findings_out: List[Dict[str, Any]] = []
    org_types = ["Organization", "Corporation", "Brand"]
    org_blocks = [b for b in blocks if any(has_type(b, t) for t in org_types)]

    if not org_blocks:
        findings_out.append(finding(
            title="Missing Organization Schema Markup",
            severity="medium",
            evidence=(
                "Page lacks Schema.org 'Organization' or 'Brand' definition. "
                "AI engines cannot establish canonical knowledge-graph identity."
            ),
            action_summary=(
                "Add Schema.org Organization markup specifying legalName, url, "
                "logo, and sameAs authoritative links."
            ),
            action_priority="medium",
            confidence=0.90,
        ))
        return findings_out

    for org in org_blocks:
        same_as = org.get("sameAs")
        missing_same_as = (
            not same_as
            or (isinstance(same_as, list) and len(same_as) == 0)
            or (isinstance(same_as, str) and not same_as.strip())
        )
        if missing_same_as:
            findings_out.append(finding(
                title="Missing Entity Disambiguation (sameAs) in Organization Schema",
                severity="medium",
                evidence=(
                    "Organization schema is present but omits 'sameAs' external "
                    "entity references (Wikidata, Wikipedia, LinkedIn, X/Twitter)."
                ),
                action_summary=(
                    "Populate 'sameAs' with canonical entity URLs "
                    "(Wikidata QID, Wikipedia page, verified social handles) "
                    "to prevent AI entity confusion."
                ),
                action_priority="medium",
                confidence=0.95,
            ))
            break

    return findings_out


# ---------------------------------------------------------------------------
# Check: FAQ schema
# ---------------------------------------------------------------------------
def check_faq_schema(
    blocks: List[Dict[str, Any]],
    soup: BeautifulSoup,
) -> List[Dict[str, Any]]:
    findings_out: List[Dict[str, Any]] = []
    has_faq_schema = any(has_type(b, "FAQPage") for b in blocks)
    if has_faq_schema:
        return findings_out

    faq_pattern = re.compile(r"(faq|frequently asked|questions)", re.I)
    faq_headings = [
        tag
        for tag in soup.find_all(re.compile(r"^h[2-4]$"))
        if faq_pattern.search(tag.get_text(strip=True))
    ]
    # Prevent false positives from simple navigation links: require at least one FAQ heading
    has_faq_dom = len(faq_headings) >= 1

    if has_faq_dom:
        findings_out.append(finding(
            title="FAQ Content Lacks Structured FAQPage Schema",
            severity="medium",
            evidence=(
                "Found FAQ / question elements in page DOM "
                f"({len(faq_headings)} FAQ heading(s) detected), "
                "but no Schema.org 'FAQPage' JSON-LD is declared."
            ),
            action_summary=(
                "Wrap FAQ sections in Schema.org 'FAQPage' markup containing "
                "'Question' and 'acceptedAnswer' entities for direct AI retrieval."
            ),
            action_priority="medium",
            confidence=0.80,
        ))
    return findings_out


# ---------------------------------------------------------------------------
# Core audit logic on parsed DOM
# ---------------------------------------------------------------------------
def _audit_structured_data_soup(
    soup: BeautifulSoup,
    norm_url: str,
) -> List[Dict[str, Any]]:
    findings_out: List[Dict[str, Any]] = []
    blocks = extract_json_ld_blocks(soup)

    if not blocks:
        findings_out.append(finding(
            title="Missing Machine-Readable Structured Data (JSON-LD)",
            severity="high",
            evidence=(
                f"Found 0 valid <script type='application/ld+json'> blocks on {norm_url}. "
                "AI search crawlers cannot deterministically extract entities or facts."
            ),
            action_summary=(
                "Add Schema.org JSON-LD markup (Organization at minimum, plus "
                "Product/FAQPage/Article where relevant) so AI engines can extract "
                "unambiguous facts."
            ),
            action_priority="high",
            confidence=1.0,
        ))
        return findings_out

    types_found: set = set()
    for b in blocks:
        types_found.update(get_types(b))

    if not (types_found & {t for t in RELEVANT_TYPES}):
        findings_out.append(finding(
            title="JSON-LD Present but Missing Key Entity Types",
            severity="high",
            evidence=(
                f"Found JSON-LD block(s) with type(s) {sorted(types_found) or 'unknown'}, "
                "but none matched Product, Organization, FAQPage, or Article."
            ),
            action_summary=(
                "Add or correct @type values to a recognised Schema.org entity type "
                "relevant to the page (Product, Organization, FAQPage, Article)."
            ),
            action_priority="high",
            confidence=0.93,
        ))

    findings_out.extend(check_product_schema(blocks, soup))
    findings_out.extend(check_organization_schema(blocks))
    findings_out.extend(check_faq_schema(blocks, soup))
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
        resp, html_text, soup = context.get_root_page()
    else:
        session = make_session(verify_ssl=verify_ssl)
        resp = polite_get(norm_url, HEADERS_BROWSER, timeout=timeout,
                          verify_ssl=verify_ssl, session=session)
        html_text = resp.text if resp is not None else None
        soup = None

    if resp is None:
        findings_out.append(finding(
            title="Could Not Fetch Page for Structured Data Check",
            severity="medium",
            evidence=f"Network request to {norm_url} failed or timed out.",
            action_summary="Ensure the page is publicly reachable so structured data can be validated.",
            action_priority="medium",
            confidence=1.0,
        ))
        return findings_out

    if resp.status_code >= 400:
        return findings_out

    if soup is None and html_text:
        soup = BeautifulSoup(html_text, _PARSER)

    if soup is None:
        return findings_out

    return _audit_structured_data_soup(soup, norm_url)


def audit_structured_data(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify_ssl: bool = True,
    html_text: Optional[str] = None,
    context: Optional[AuditContext] = None,
) -> List[Dict[str, Any]]:
    norm_url = normalize_url(url)
    if html_text:
        soup = BeautifulSoup(html_text, _PARSER)
        return _audit_structured_data_soup(soup, norm_url)
    return run_checks(norm_url, timeout=timeout, verify_ssl=verify_ssl, context=context)


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="structured-data-audit standalone runner")
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
