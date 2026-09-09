#!/usr/bin/env python3
"""
tests/test_bug_fixes.py

Comprehensive test suite verifying all bug fixes across the Brand AI Readiness Audit:
1. SSRF security holes (BSD shorthand blocking, DNS resolution validation, redirect SSRF, IPv6 domain_of).
2. Crawl & Render audit (robots.txt comment persistence, modern SPA CSR detection, bot alignment, subpath support).
3. Freshness corroboration (sitemap SSRF validation, case-insensitive canonical tag, gzipped sitemaps, RFC 2822 dates).
4. Structured Data audit (price: 0/0.0 non-falsy check, AggregateOffer support, FAQ nav-link false positive prevention, interface alignment).
5. Engagement audit (header h1 wrapper support, nested heading anchors, modal deduplication).
6. Orchestrator (path traversal enforcement, inspect.signature TypeError duplicate execution avoidance, SSRF pillar mapping).
7. Sample report schema synchronization.
"""

from __future__ import annotations

import os
import sys
import gzip
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: F401

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SKILLS_DIR = os.path.join(_REPO_ROOT, "skills")
_SHARED_DIR = os.path.join(_SKILLS_DIR, "shared")
for p in (_REPO_ROOT, _SKILLS_DIR, _SHARED_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from utils import (
    is_safe_target_url, domain_of, polite_get, get_finding_category,
    calculate_geo_score, calculate_pillar_scores,
)
from check_crawler_render import (
    parse_robots_txt, is_bot_blocked, check_robots_txt,
    check_csr_dependency, AI_BOTS, MAJOR_AI_BOTS, CORE_AI_SEARCH_BOTS,
)
from check_freshness import (
    check_temporal_metadata, check_sitemap, _parse_date,
)
from check_structured_data import (
    check_product_schema, check_faq_schema, audit_structured_data, run_checks as sd_run_checks,
    extract_json_ld_blocks,
)
from check_engagement import (
    check_direct_answer, check_deep_link_anchors, check_modal_noise,
)
from run_audit import _safe_write_output, run_full_audit
from bs4 import BeautifulSoup


class TestSSRFAndIPv6Fixes(unittest.TestCase):
    """Test SSRF security enhancements and IPv6 domain extraction."""

    def test_block_bsd_shorthand_ip_0(self):
        safe, err = is_safe_target_url("http://0")
        self.assertFalse(safe)
        self.assertIn("shorthand", err.lower())

    def test_block_bsd_shorthand_ip_127_1(self):
        safe, err = is_safe_target_url("http://127.1")
        self.assertFalse(safe)
        self.assertIn("shorthand", err.lower())

    def test_block_bsd_shorthand_octal_and_hex(self):
        for raw in ["http://0177.0.0.1", "http://0x7f000001", "http://127.0.1"]:
            safe, err = is_safe_target_url(raw)
            self.assertFalse(safe, f"Expected {raw} to be blocked as shorthand IP")

    def test_domain_of_ipv6_rate_limiting_key(self):
        url_ipv6 = "https://[2001:db8::1]:8080/audit/catalog"
        domain = domain_of(url_ipv6)
        self.assertEqual(domain, "2001:db8::1", "IPv6 domain must be parsed without brackets or port")

    def test_domain_of_standard_url(self):
        url = "https://example.com:443/products"
        self.assertEqual(domain_of(url), "example.com")

    @patch("socket.getaddrinfo")
    def test_dns_resolution_blocks_private_ip(self, mock_gai):
        mock_gai.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 80))
        ]
        safe, err = is_safe_target_url("https://malicious-internal-rebind.org")
        self.assertFalse(safe)
        self.assertIn("prohibited IP", err)

    @patch("requests.Session.get")
    def test_redirect_ssrf_blocked_in_polite_get(self, mock_get):
        redirect_resp = MagicMock()
        redirect_resp.is_redirect = True
        redirect_resp.status_code = 302
        redirect_resp.headers = {"Location": "http://169.254.169.254/latest/meta-data/"}

        mock_get.return_value = redirect_resp

        resp = polite_get("https://safe-domain.example.com", headers={"User-Agent": "test"})
        self.assertIsNone(resp, "Redirect to internal metadata IP must be blocked and return None")

    def test_domain_of_schemeless_url_with_port(self):
        url = "example.com:8080/path"
        self.assertEqual(domain_of(url), "example.com")

    def test_normalize_url_bare_ipv6(self):
        from utils import normalize_url
        norm = normalize_url("2001:db8::1")
        self.assertEqual(norm, "https://[2001:db8::1]")
        self.assertEqual(domain_of("2001:db8::1"), "2001:db8::1")

    def test_block_cgnat_and_benchmarking_non_global_ips(self):
        safe_cgnat, _ = is_safe_target_url("http://100.64.0.1")
        self.assertFalse(safe_cgnat, "Carrier-Grade NAT 100.64.0.0/10 must be blocked")
        safe_bench, _ = is_safe_target_url("http://198.18.0.1")
        self.assertFalse(safe_bench, "Benchmarking 198.18.0.0/15 must be blocked")

    def test_ssrf_finding_mapped_to_crawl_render_pillar(self):
        cat = get_finding_category("SSRF / Prohibited Target Host Blocked")
        self.assertEqual(cat, "crawl_render")


class TestCrawlRenderAuditFixes(unittest.TestCase):
    """Test robots.txt comment parsing, modern SPA CSR detection, bot alignment, and subpaths."""

    def test_robots_txt_comment_does_not_wipe_user_agent(self):
        txt = """
User-agent: GPTBot
# Notice: internal disallow comment
Disallow: /private/
"""
        rules = parse_robots_txt(txt)
        self.assertIn("gptbot", rules)
        self.assertIn("/private/", rules["gptbot"]["disallow"],
                      "Comments between User-agent and Disallow must NOT wipe current_agents")

    def test_modern_spa_csr_detection_with_external_script(self):
        html = """<!DOCTYPE html>
<html>
<head>
  <script type="module" src="/assets/index.c3f81e2b.js"></script>
</head>
<body>
  <div id="root"></div>
</body>
</html>"""
        findings = check_csr_dependency("https://modern-spa.test", html_text=html)
        csr_findings = [f for f in findings if "Client-Side JavaScript" in f["title"]]
        self.assertEqual(len(csr_findings), 1,
                         "Modern Vite/CRA SPA with empty #root and minimal words must trigger CSR finding")

    def test_major_ai_bots_consistency_and_applebot_extended(self):
        self.assertIn("Applebot-Extended", AI_BOTS)
        self.assertIn("applebot-extended", MAJOR_AI_BOTS)
        self.assertIn("OAI-SearchBot", AI_BOTS)
        self.assertIn("Claude-SearchBot", AI_BOTS)

        rules = {
            "applebot-extended": {"allow": [], "disallow": ["/"], "crawl_delay": None}
        }
        self.assertTrue(is_bot_blocked(rules, "Applebot-Extended", "/"))

    def test_claude_user_and_claude_web_in_major_bots(self):
        self.assertIn("Claude-Web", AI_BOTS)
        self.assertIn("Claude-User", AI_BOTS)
        self.assertIn("claude-web", MAJOR_AI_BOTS)
        self.assertIn("claude-user", MAJOR_AI_BOTS)

    def test_secondary_ai_bots_restricted_emits_low_severity_when_core_allowed(self):
        self.assertIn("gptbot", CORE_AI_SEARCH_BOTS)
        self.assertIn("claudebot", CORE_AI_SEARCH_BOTS)
        self.assertIn("perplexitybot", CORE_AI_SEARCH_BOTS)
        self.assertIn("google-extended", CORE_AI_SEARCH_BOTS)

        # When core search bots are allowed but secondary bots (like Applebot-Extended) are disallowed
        robots = """User-agent: *
Disallow: /
User-agent: GPTBot
User-agent: ChatGPT-User
User-agent: OAI-SearchBot
User-agent: ClaudeBot
User-agent: Claude-User
User-agent: Claude-SearchBot
User-agent: PerplexityBot
User-agent: Google-Extended
Allow: /
"""
        findings = check_robots_txt("https://streamer.test", robots_txt=robots)
        titles = [f["title"] for f in findings]
        self.assertNotIn("AI Web Crawlers Blocked in robots.txt", titles)
        secondary_findings = [f for f in findings if f["title"] == "Secondary AI Crawlers Restricted in robots.txt"]
        self.assertEqual(len(secondary_findings), 1)
        self.assertEqual(secondary_findings[0]["severity"], "low")

    def test_is_bot_blocked_rfc9309_wildcards_and_exact(self):
        rules = {
            "gptbot": {
                "allow": ["/public/*", "/items$"],
                "disallow": ["/*/private", "/checkout$", "/*.php$"],
                "crawl_delay": None,
            }
        }
        self.assertTrue(is_bot_blocked(rules, "GPTBot", "/users/private"))
        self.assertTrue(is_bot_blocked(rules, "GPTBot", "/checkout"))
        self.assertFalse(is_bot_blocked(rules, "GPTBot", "/checkout/summary"))
        self.assertTrue(is_bot_blocked(rules, "GPTBot", "/index.php"))
        self.assertFalse(is_bot_blocked(rules, "GPTBot", "/index.php/sub"))
        self.assertFalse(is_bot_blocked(rules, "GPTBot", "/public/docs"))

    def test_is_bot_blocked_supports_anchors_and_subpaths(self):
        rules = {
            "*": {"allow": [], "disallow": ["/checkout$", "/api/"], "crawl_delay": None}
        }
        self.assertTrue(is_bot_blocked(rules, "GPTBot", "/checkout"))
        self.assertFalse(is_bot_blocked(rules, "GPTBot", "/checkout/success"))
        self.assertTrue(is_bot_blocked(rules, "GPTBot", "/api/v1/users"))


class TestFreshnessAuditFixes(unittest.TestCase):
    """Test sitemap SSRF checks, case-insensitive canonical tag, gzipped sitemaps, and date parsing."""

    def test_relative_sitemap_url_discovered_and_validated(self):
        from check_freshness import _discover_sitemap_urls
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "User-agent: *\nSitemap: /relative_sitemap.xml\n"
        with patch("check_freshness.polite_get", return_value=mock_resp):
            cands = _discover_sitemap_urls("https://example.com")
            self.assertIn("https://example.com/relative_sitemap.xml", cands)

    def test_case_insensitive_canonical_tag_recognized(self):
        html = """<html><head>
        <link rel="Canonical" href="https://example.com/canonical-page">
        </head><body><p>Content</p></body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        findings = check_temporal_metadata("https://example.com/canonical-page", soup, {})
        canonical_missing = [f for f in findings if "Missing Canonical" in f["title"]]
        self.assertEqual(len(canonical_missing), 0,
                         "rel='Canonical' with capital C must be recognized")

    def test_rfc2822_date_parsing_helper(self):
        dt1 = _parse_date("Mon, 01 Aug 2026 12:00:00 GMT")
        self.assertIsNotNone(dt1)
        self.assertEqual(dt1.year, 2026)

        dt2 = _parse_date("2026-08-01T00:00:00Z")
        self.assertIsNotNone(dt2)
        self.assertEqual(dt2.year, 2026)

        dt3 = _parse_date("2026-08")
        self.assertIsNotNone(dt3)
        self.assertEqual(dt3.year, 2026)
        self.assertEqual(dt3.month, 8)

        dt4 = _parse_date("2026")
        self.assertIsNotNone(dt4)
        self.assertEqual(dt4.year, 2026)

    def test_gzipped_sitemap_decompression_and_lastmod(self):
        xml_content = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://example.com/item</loc>
    <lastmod>2026-08-01</lastmod>
  </url>
</urlset>"""
        gz_bytes = gzip.compress(xml_content)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = gz_bytes
        mock_resp.text = ""

        with patch("check_freshness.polite_get", return_value=mock_resp):
            findings = check_sitemap("https://example.com")
            not_found = [f for f in findings if "Sitemap Not Found" in f["title"]]
            stale = [f for f in findings if "Stale" in f["title"]]
            self.assertEqual(len(not_found), 0, "Gzipped sitemap must be recognized and parsed")
            self.assertEqual(len(stale), 0, "Recent lastmod in gzipped sitemap must not be stale")


class TestStructuredDataFixes(unittest.TestCase):
    """Test price: 0/0.0 non-falsy check, AggregateOffer, and FAQ false positive elimination."""

    def test_price_zero_and_float_zero_not_flagged(self):
        soup = BeautifulSoup("<html><body>Product</body></html>", "html.parser")
        blocks = [
            {
                "@context": "https://schema.org/",
                "@type": "Product",
                "name": "Free Community Tier",
                "image": "https://example.com/free.png",
                "description": "Free open-source tier.",
                "offers": {
                    "@type": "Offer",
                    "price": 0,
                    "priceCurrency": "USD",
                    "availability": "https://schema.org/InStock",
                },
            }
        ]
        findings = check_product_schema(blocks, soup)
        missing_price = [f for f in findings if "Missing Price" in f["title"]]
        self.assertEqual(len(missing_price), 0, "price: 0 must not be flagged as missing")

    def test_aggregate_offer_supported(self):
        soup = BeautifulSoup("<html><body>Product</body></html>", "html.parser")
        blocks = [
            {
                "@context": "https://schema.org/",
                "@type": "Product",
                "name": "Enterprise Subscription",
                "image": "https://example.com/ent.png",
                "description": "Flexible tiers.",
                "offers": {
                    "@type": "AggregateOffer",
                    "lowPrice": "49.00",
                    "highPrice": "199.00",
                    "priceCurrency": "USD",
                    "availability": "https://schema.org/InStock",
                },
            }
        ]
        findings = check_product_schema(blocks, soup)
        missing_price = [f for f in findings if "Incomplete Product Schema" in f["title"]]
        self.assertEqual(len(missing_price), 0, "AggregateOffer with lowPrice/highPrice must be valid")

    def test_aggregate_offer_without_availability_not_flagged(self):
        soup = BeautifulSoup("<html><body>Product</body></html>", "html.parser")
        blocks = [
            {
                "@context": "https://schema.org/",
                "@type": "Product",
                "name": "Multi-Vendor Item",
                "image": "https://example.com/item.png",
                "description": "Aggregated item pricing.",
                "offers": {
                    "@type": "AggregateOffer",
                    "lowPrice": "19.99",
                    "highPrice": "49.99",
                    "priceCurrency": "USD",
                },
            }
        ]
        findings = check_product_schema(blocks, soup)
        self.assertEqual(len(findings), 0, "AggregateOffer without availability should not produce findings")

    def test_no_false_positive_faq_from_simple_nav_link(self):
        html = """<html><body>
        <nav><a class="faq-link" href="/help/faq">FAQ</a></nav>
        <h1>About Us</h1>
        <p>We build great tools.</p>
        </body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        blocks = extract_json_ld_blocks(soup)
        findings = check_faq_schema(blocks, soup)
        faq_findings = [f for f in findings if "FAQ Content Lacks" in f["title"]]
        self.assertEqual(len(faq_findings), 0,
                         "Simple nav link with 'faq' class must NOT trigger FAQ schema finding without FAQ headings")

    def test_run_checks_and_audit_structured_data_aligned(self):
        html = """<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Thing","name":"Unknown Entity"}
</script>
</head><body><p>Content</p></body></html>"""
        findings_direct = audit_structured_data("https://align-test.test", html_text=html)
        self.assertTrue(any("Missing Key Entity Types" in f["title"] for f in findings_direct),
                        "audit_structured_data must run the full entity type check exactly like run_checks")


class TestEngagementAuditFixes(unittest.TestCase):
    """Test header h1 wrapper support, nested heading anchors, and modal deduplication."""

    def test_header_wrapper_around_h1_with_sibling_p_no_false_positive(self):
        html = """<html><body>
<header>
    <h1>Product Analytics Cloud</h1>
</header>
<p>An enterprise-ready product analytics platform delivering real-time user insights and behavioral tracking.</p>
</body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        findings = check_direct_answer(soup)
        buried = [f for f in findings if "Buried Direct Answer" in f["title"]]
        self.assertEqual(len(buried), 0,
                         "<header><h1> followed by concise paragraph must NOT flag buried answer")

    def test_direct_answer_ignores_preamble_paragraph_before_h1(self):
        html = """<html><body>
        <main>
            <p class="tagline">Welcome to our store founded back in 2010 with quality items</p>
            <h1>Product Catalog</h1>
            <div><button>Browse</button></div>
        </main>
        </body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        findings = check_direct_answer(soup)
        buried = [f for f in findings if "Buried Direct Answer" in f["title"]]
        self.assertEqual(len(buried), 1, "Preamble paragraph before <h1> must NOT prevent buried answer finding")

    def test_nested_heading_anchor_detected(self):
        html = """<html><body>
<h2><span id="overview" class="anchor"></span>Overview</h2>
<h2><span id="architecture" class="anchor"></span>Architecture</h2>
<h2><span id="security" class="anchor"></span>Security</h2>
</body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        findings = check_deep_link_anchors(soup)
        missing_anchors = [f for f in findings if "Missing Deep-Link" in f["title"]]
        self.assertEqual(len(missing_anchors), 0,
                         "Headings with nested <span id='...'> must be counted as anchored")

    def test_modal_deduplication(self):
        html = """<html><body>
<div id="newsletter-modal" class="modal newsletter-popup">Subscribe to our newsletter!</div>
</body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        findings = check_modal_noise(html, soup)
        modal_findings = [f for f in findings if "Intrusive Modal" in f["title"]]
        self.assertEqual(len(modal_findings), 1)
        evidence = modal_findings[0]["evidence"]
        self.assertEqual(evidence.count("newsletter-modal"), 1)

    def test_modal_noise_deduplicates_nested_bootstrap_modal(self):
        html = """<html><body>
        <div id="newsletter-modal" class="modal">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-body"><p>Join our newsletter</p></div>
                </div>
            </div>
        </div>
        </body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        findings = check_modal_noise(html, soup)
        self.assertEqual(len(findings), 1)
        evidence = findings[0]["evidence"]
        self.assertIn("newsletter-modal", evidence)
        self.assertNotIn("modal-dialog", evidence)


class TestOrchestratorFixes(unittest.TestCase):
    """Test path traversal guard and TypeError single-execution in orchestrator."""

    def test_safe_write_output_blocks_path_traversal(self):
        with self.assertRaises(ValueError):
            _safe_write_output("../../escape_dir/report.json", "{}")

    def test_safe_write_output_rejects_empty_path_and_directory(self):
        with self.assertRaises(ValueError):
            _safe_write_output("", "{}")
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                _safe_write_output(temp_dir, "{}")

    def test_type_error_inside_subskill_executes_only_once(self):
        mock_mod = MagicMock()
        call_count = 0

        def flaky_run_checks(url, timeout=10, verify_ssl=True, context=None):
            nonlocal call_count
            call_count += 1
            raise TypeError("Internal NoneType subscript error inside skill")

        mock_mod.run_checks = flaky_run_checks

        with patch("run_audit.SUB_SKILLS", [("crawl-render-audit", "check_crawler_render.py")]), \
             patch("run_audit.load_skill_module", return_value=mock_mod):
            report = run_full_audit("https://type-error-test.test")
            self.assertEqual(call_count, 1,
                             "Internal TypeError inside skill must NOT trigger duplicate retry")
            self.assertTrue(any("Execution Notice" in f["title"] for f in report["findings"]))

    def test_sample_audit_report_schema_synchronized(self):
        sample_path = Path(_REPO_ROOT) / "sample_audit_report.json"
        self.assertTrue(sample_path.is_file())

        with open(sample_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for req_key in ("site", "audited_at", "geo_score", "pillar_scores", "summary", "findings"):
            self.assertIn(req_key, data)

        for pillar in ("crawl_render", "structured_data", "freshness_security", "engagement"):
            self.assertIn(pillar, data["pillar_scores"])

        for sum_key in ("total_findings", "critical", "high", "medium", "low"):
            self.assertIn(sum_key, data["summary"])

        for f in data["findings"]:
            self.assertIn("confidence", f)
            self.assertIsInstance(f["confidence"], float)


if __name__ == "__main__":
    unittest.main()
