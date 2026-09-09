#!/usr/bin/env python3
"""
tests/test_skills.py

Unit and integration tests for Brand AI Readiness Audit Marketplace.
Validates detection heuristics against simulated scenarios and orchestrator output.

Fix: @patch targets use module-level names pre-loaded by conftest.py into
sys.modules, ensuring patches resolve correctly in all execution orders.
Orchestrator integration tests patch at load_skill_module level (correct pattern).
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: F401

from check_crawler_render import parse_robots_txt, is_bot_blocked, check_csr_dependency
from check_structured_data import audit_structured_data, extract_json_ld_blocks, check_faq_schema
from check_freshness import audit_freshness
from check_engagement import audit_engagement
from run_audit import run_full_audit


class TestRobotsTxtParser(unittest.TestCase):
    """Tests for the RFC 9309-compliant robots.txt parser."""

    def test_detects_blocked_gptbot(self):
        robots = """
User-agent: Googlebot
Allow: /

User-agent: GPTBot
Disallow: /

User-agent: PerplexityBot
Disallow: /catalog
"""
        rules = parse_robots_txt(robots)
        self.assertIn("gptbot", rules)
        self.assertIn("/", rules["gptbot"]["disallow"])
        self.assertIn("perplexitybot", rules)
        self.assertIn("/catalog", rules["perplexitybot"]["disallow"])

    def test_allow_overrides_disallow_rfc9309(self):
        """
        RFC 9309 §2.2.1: Allow: /products must override Disallow: / for /products path.
        """
        robots = """
User-agent: GPTBot
Disallow: /
Allow: /products
"""
        rules = parse_robots_txt(robots)
        # Bot IS blocked from / (disallow is more specific than no allow for /)
        self.assertTrue(is_bot_blocked(rules, "GPTBot", "/"))
        # Bot is NOT blocked from /products (allow is more specific)
        self.assertFalse(is_bot_blocked(rules, "GPTBot", "/products"))

    def test_wildcard_blocks_all_bots(self):
        robots = """
User-agent: *
Disallow: /
"""
        rules = parse_robots_txt(robots)
        self.assertTrue(is_bot_blocked(rules, "GPTBot", "/"))
        self.assertTrue(is_bot_blocked(rules, "ClaudeBot", "/"))

    def test_crawl_delay_parsed(self):
        robots = """
User-agent: GPTBot
Disallow: /private
Crawl-delay: 2
"""
        rules = parse_robots_txt(robots)
        self.assertEqual(rules["gptbot"]["crawl_delay"], 2.0)

    def test_empty_disallow_allows_all(self):
        """Empty Disallow: means 'allow everything'."""
        robots = """
User-agent: GPTBot
Disallow:
"""
        rules = parse_robots_txt(robots)
        self.assertFalse(is_bot_blocked(rules, "GPTBot", "/"))

    def test_no_rules_means_allowed(self):
        rules = parse_robots_txt("")
        self.assertFalse(is_bot_blocked(rules, "GPTBot", "/"))


class TestCrawlRenderAudit(unittest.TestCase):

    def test_csr_detection_flags_empty_spa_root(self):
        """Empty #root container + heavy script payload = CSR finding."""
        # Build inline JS >40KB
        large_js = "x" * 45_000
        html_spa = f"""<!DOCTYPE html>
<html>
<head>
    <script>{large_js}</script>
    <script>var a=1;</script><script>var b=1;</script>
    <script>var c=1;</script><script>var d=1;</script>
    <script>var e=1;</script><script>var f=1;</script>
    <script>var g=1;</script>
</head>
<body>
    <div id="root"></div>
</body>
</html>"""
        findings = check_csr_dependency("https://mock-spa.test", html_text=html_spa)
        csr = [f for f in findings if "Client-Side JavaScript" in f["title"]]
        self.assertTrue(len(csr) > 0, "SPA with empty #root and large JS must flag CSR")

    def test_csr_no_false_positive_for_thin_ssr_page(self):
        """A thin but SSR page (no SPA root container) must NOT trigger CSR finding."""
        html_ssr = """<!DOCTYPE html>
<html><head><title>Login</title></head>
<body><h1>Sign In</h1><form><input type="email"/><button>Login</button></form></body>
</html>"""
        findings = check_csr_dependency("https://mock-login.test", html_text=html_ssr)
        csr = [f for f in findings if "Client-Side" in f["title"]]
        self.assertEqual(len(csr), 0, "Thin SSR login page must not be flagged as CSR")

    def test_csr_no_false_positive_for_minimal_product_page(self):
        """Minimal product page with real content but few words: no CSR finding."""
        html_product = """<!DOCTYPE html>
<html><head><title>Widget Pro</title></head>
<body>
  <h1>Widget Pro</h1>
  <p>$49.99. In stock. Ships in 2 days.</p>
  <button>Add to Cart</button>
</body>
</html>"""
        findings = check_csr_dependency("https://mock-product.test", html_text=html_product)
        csr = [f for f in findings if "Client-Side" in f["title"]]
        self.assertEqual(len(csr), 0, "Minimal SSR product page must not flag CSR")


class TestStructuredDataAudit(unittest.TestCase):

    def test_missing_json_ld_detected(self):
        html = "<html><body><h1>Hello World</h1></body></html>"
        findings = audit_structured_data("https://mock-no-schema.test", html_text=html)
        self.assertTrue(any("Missing Machine-Readable Structured Data" in f["title"]
                            for f in findings))

    def test_incomplete_product_schema_flagged(self):
        html = """<html>
<head>
<script type="application/ld+json">
{
  "@context": "https://schema.org/",
  "@type": "Product",
  "name": "Super Sneaker",
  "image": "https://example.com/shoe.jpg",
  "description": "High performance running shoe."
}
</script>
</head>
<body><h1>Super Sneaker</h1></body>
</html>"""
        findings = audit_structured_data("https://mock-prod.test", html_text=html)
        self.assertTrue(any("Incomplete Product Schema" in f["title"]
                            for f in findings))

    def test_complete_product_schema_no_finding(self):
        html = """<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org/",
  "@type": "Product",
  "name": "Widget",
  "image": "https://example.com/w.jpg",
  "description": "A great widget.",
  "offers": {
    "@type": "Offer",
    "price": "9.99",
    "priceCurrency": "USD",
    "availability": "https://schema.org/InStock"
  }
}
</script>
</head><body><h1>Widget</h1></body></html>"""
        findings = audit_structured_data("https://mock-complete.test", html_text=html)
        product_findings = [f for f in findings if "Product" in f["title"]]
        self.assertEqual(len(product_findings), 0, "Complete product schema must not produce a finding")

    def test_faq_heading_with_nested_tags_detected(self):
        """FAQ headings with nested <span> must be detected — not just string= match."""
        html = """<html><body>
<h2><span>FAQ</span> Section</h2>
<p>Q: Something? A: Yes.</p>
</body></html>"""
        from bs4 import BeautifulSoup
        soup   = BeautifulSoup(html, "html.parser")
        blocks = extract_json_ld_blocks(soup)
        findings = check_faq_schema(blocks, soup)
        self.assertTrue(any("FAQ" in f["title"] for f in findings),
                        "FAQ heading with nested <span> must be detected")

    def test_organization_sameAs_missing_flagged(self):
        html = """<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Organization","name":"Acme Corp","url":"https://acme.com"}
</script>
</head><body><h1>Acme</h1></body></html>"""
        findings = audit_structured_data("https://mock-org.test", html_text=html)
        self.assertTrue(any("sameAs" in f["title"] for f in findings))


class TestFreshnessAudit(unittest.TestCase):

    def test_stale_copyright_detected(self):
        html = """<html><body>
    <h1>Company</h1>
    <footer>Copyright &copy; 2019 Acme Corp. All rights reserved.</footer>
</body></html>"""
        findings = audit_freshness("https://mock-freshness.test",
                                   html_text=html, headers={})
        self.assertTrue(any("Outdated Copyright Year" in f["title"]
                            for f in findings))

    def test_current_copyright_no_finding(self):
        """Copyright year = current year must NOT produce a finding."""
        from utils import current_year
        html = f"""<html><body>
    <footer>Copyright &copy; {current_year()} Company Inc.</footer>
</body></html>"""
        findings = audit_freshness("https://mock-current.test",
                                   html_text=html, headers={})
        stale = [f for f in findings if "Copyright" in f["title"]]
        self.assertEqual(len(stale), 0, "Current copyright year must not be flagged")

    def test_missing_canonical_detected(self):
        html = "<html><head><title>Test</title></head><body><h1>Page</h1></body></html>"
        findings = audit_freshness("https://mock-canon.test",
                                   html_text=html, headers={})
        self.assertTrue(any("Canonical" in f["title"] for f in findings))

    def test_hsts_missing_detected_on_https(self):
        html = "<html><head><link rel='canonical' href='https://x.com/'/></head><body></body></html>"
        findings = audit_freshness("https://mock-hsts.test",
                                   html_text=html,
                                   headers={"Content-Type": "text/html"})
        hsts = [f for f in findings if "HSTS" in f["title"]]
        self.assertTrue(len(hsts) > 0, "Missing HSTS header must be detected on https:// URLs")

    def test_hsts_not_flagged_for_http(self):
        """HSTS check must NOT fire for plain http:// targets."""
        html = "<html><head><link rel='canonical' href='http://x.com/'/></head><body></body></html>"
        findings = audit_freshness("http://mock-http.test",
                                   html_text=html, headers={})
        hsts = [f for f in findings if "HSTS" in f["title"]]
        self.assertEqual(len(hsts), 0, "HSTS must not be flagged for plain http:// sites")


class TestEngagementAudit(unittest.TestCase):

    def test_buried_answer_detected(self):
        html = """<html><body>
    <header>
        <h1>Cloud Data Platform</h1>
        <div style="height:600px;"></div>
        <div class="carousel">Slide 1</div>
    </header>
</body></html>"""
        findings = audit_engagement("https://mock-engagement.test", html_text=html)
        self.assertTrue(any("Buried Direct Answer" in f["title"] for f in findings))

    def test_no_h1_flagged(self):
        html = "<html><body><p>No heading here</p></body></html>"
        findings = audit_engagement("https://mock-noh1.test", html_text=html)
        self.assertTrue(any("No H1" in f["title"] for f in findings))

    def test_modal_overlay_detected(self):
        html = """<html><body>
<h1>Welcome</h1><p>Great product for you today. Order now and save big!</p>
<div class="modal" id="newsletter-signup">Subscribe now!</div>
</body></html>"""
        findings = audit_engagement("https://mock-modal.test", html_text=html)
        self.assertTrue(any("Modal" in f["title"] for f in findings))


class TestConfidenceScores(unittest.TestCase):
    """Verify every finding carries a valid 0.0-1.0 confidence score."""

    def _collect_findings(self, html_text: str) -> list:
        url     = "https://mock-confidence.test"
        results = []
        results += audit_structured_data(url, html_text=html_text)
        results += audit_freshness(url, html_text=html_text, headers={})
        results += audit_engagement(url, html_text=html_text)
        results += check_csr_dependency(url, html_text=html_text)
        return results

    def test_all_findings_have_valid_confidence(self):
        html = "<html><body><h1>Test</h1></body></html>"
        for f in self._collect_findings(html):
            self.assertIn("confidence", f,
                          f"Finding '{f.get('title')}' is missing confidence field")
            conf = f["confidence"]
            self.assertIsInstance(conf, float)
            self.assertGreaterEqual(conf, 0.0)
            self.assertLessEqual(conf, 1.0)


class TestOrchestratorIntegration(unittest.TestCase):
    """Integration tests patching at load_skill_module level (correct pattern)."""

    def _make_mock_module(self, findings_list=None):
        mock_mod = MagicMock()
        mock_mod.run_checks.return_value = findings_list or []
        return mock_mod

    @patch("run_audit.load_skill_module")
    def test_orchestrator_schema_compliance(self, mock_load):
        sample_finding = {
            "title":    "Missing Machine-Readable Structured Data (JSON-LD)",
            "severity": "high",
            "evidence": "Found 0 valid JSON-LD blocks.",
            "suggested_action": {"summary": "Add Schema.org JSON-LD.", "priority": "high"},
            "confidence": 1.0,
        }
        mock_load.return_value = self._make_mock_module([sample_finding])
        report = run_full_audit("https://schema-test.com")

        # Required root keys
        for key in ("site", "audited_at", "summary", "findings"):
            self.assertIn(key, report)

        # Summary structure — all 5 keys including low
        summary = report["summary"]
        for key in ("total_findings", "critical", "high", "medium", "low"):
            self.assertIn(key, summary)
        self.assertEqual(summary["total_findings"], len(report["findings"]))

        # Each finding must comply with the schema
        for f in report["findings"]:
            self.assertRegex(f["id"], r"^F-\d{3}$")
            self.assertIn(f["severity"], ("critical", "high", "medium", "low"))
            self.assertIsInstance(f["evidence"], str)
            self.assertIn("summary",  f["suggested_action"])
            self.assertIn("priority", f["suggested_action"])
            self.assertIn(f["suggested_action"]["priority"], ("high", "medium", "low"))
            self.assertIn("confidence", f)
            self.assertIsInstance(f["confidence"], float)

    @patch("run_audit.load_skill_module")
    def test_deduplication_keeps_same_title_diff_evidence(self, mock_load):
        """Two findings with identical title but different evidence must BOTH be kept."""
        f1 = {
            "title": "Incomplete Product Schema: Missing Price or Availability",
            "severity": "high",
            "evidence": "Product A is missing price field.",
            "suggested_action": {"summary": "Fix A.", "priority": "high"},
            "confidence": 0.9,
        }
        f2 = {
            "title": "Incomplete Product Schema: Missing Price or Availability",
            "severity": "high",
            "evidence": "Product B availability field is absent.",
            "suggested_action": {"summary": "Fix B.", "priority": "high"},
            "confidence": 0.9,
        }
        mock_load.return_value = self._make_mock_module([f1, f2])
        report = run_full_audit("https://dedup-test.com")
        titles = [f["title"] for f in report["findings"]]
        self.assertGreaterEqual(
            titles.count(f1["title"]), 2,
            "Distinct findings with same title must both be retained",
        )

    @patch("run_audit.load_skill_module")
    def test_low_severity_preserved_not_upcasted(self, mock_load):
        low_finding = {
            "title":    "Outdated Copyright Year in Footer",
            "severity": "low",
            "evidence": "Footer shows 2019.",
            "suggested_action": {"summary": "Update year.", "priority": "low"},
            "confidence": 0.80,
        }
        mock_load.return_value = self._make_mock_module([low_finding])
        report = run_full_audit("https://low-sev-test.com")
        self.assertEqual(report["summary"]["low"], 1)
        self.assertEqual(report["findings"][0]["severity"], "low",
                         "'low' severity must not be upcasted to 'medium'")

    @patch("run_audit.load_skill_module")
    def test_skill_crash_contained_with_notice_finding(self, mock_load):
        mock_mod = MagicMock()
        mock_mod.run_checks.side_effect = RuntimeError("Simulated skill crash")
        mock_load.return_value = mock_mod

        report = run_full_audit("https://crash-test.com")
        self.assertIn("findings", report)
        self.assertGreaterEqual(report["summary"]["total_findings"], 1)
        self.assertTrue(
            any("Notice" in f["title"] for f in report["findings"]),
            "Crash must produce an 'Execution Notice' finding, not propagate",
        )

    @patch("run_audit.load_skill_module")
    def test_interface_contract_enforced(self, mock_load):
        """Sub-skill without run_checks() must produce a contained error, not a crash."""
        mock_mod = MagicMock(spec=[])  # Empty spec — no run_checks attribute
        mock_load.return_value = mock_mod

        # Must not raise; must return a valid report
        report = run_full_audit("https://no-interface.com")
        self.assertIn("findings", report)

    @patch("run_audit.load_skill_module")
    def test_geo_score_and_pillars_computed(self, mock_load):
        """Report must include geo_score and 4-pillar scores."""
        finding_item = {
            "title": "Missing Organization Schema Markup",
            "severity": "medium",
            "evidence": "Missing org schema.",
            "suggested_action": {"summary": "Add org schema.", "priority": "medium"},
            "confidence": 0.90,
        }
        mock_load.return_value = self._make_mock_module([finding_item])
        report = run_full_audit("https://geo-test.com")
        self.assertIn("geo_score", report)
        self.assertIn("pillar_scores", report)
        self.assertEqual(len(report["pillar_scores"]), 4)
        self.assertLess(report["geo_score"], 100)

    def test_ssrf_blocks_private_ip(self):
        """SSRF protection must block private IP addresses."""
        report = run_full_audit("http://192.168.1.55")
        self.assertEqual(report["geo_score"], 10)
        self.assertTrue(any("SSRF" in f["title"] for f in report["findings"]))

    def test_mock_server_clean_site_zero_findings_100_score(self):
        """A 100% compliant site must produce 0 findings and GEO score 100."""
        from tests.mock_server import MockServer
        with MockServer() as server:
            clean_url = server.get_url("/clean")
            report = run_full_audit(clean_url)
            self.assertEqual(report["summary"]["total_findings"], 0)
            self.assertEqual(report["geo_score"], 100)
            self.assertEqual(report["pillar_scores"]["crawl_render"], 100.0)
            self.assertEqual(report["pillar_scores"]["structured_data"], 100.0)
            self.assertEqual(report["pillar_scores"]["freshness_security"], 100.0)
            self.assertEqual(report["pillar_scores"]["engagement"], 100.0)


if __name__ == "__main__":
    unittest.main()
