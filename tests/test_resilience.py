#!/usr/bin/env python3
"""
tests/test_resilience.py

Adversarial and resilience tests for Brand AI Readiness Audit.
Tests network timeouts, connection resets, malformed HTML, empty payloads,
non-ASCII text, unusual HTTP status codes, and partial responses.

Fix: @patch targets use module names pre-loaded in conftest.py, ensuring
they resolve correctly regardless of test execution order.
Orchestrator tests patch at run_audit.load_skill_module level.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch, MagicMock
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: F401

# Modules are importable directly
from check_crawler_render import run_checks as crawl_checks
from check_structured_data import run_checks as schema_checks
from check_freshness      import run_checks as freshness_checks
from check_engagement     import run_checks as engagement_checks
from run_audit            import run_full_audit


class TestResilienceAndEdgeCases(unittest.TestCase):

    # ------------------------------------------------------------------
    # crawl-render-audit resilience
    # ------------------------------------------------------------------

    def test_crawl_handles_network_timeout(self):
        """A connection timeout must not propagate as an unhandled exception."""
        with patch("check_crawler_render.polite_get", return_value=None):
            findings = crawl_checks("https://timeout-site.test", timeout=1)
        self.assertIsInstance(findings, list)

    def test_crawl_handles_403_robots_txt(self):
        """403 on robots.txt must produce a finding, not a crash."""
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        with patch("check_crawler_render.polite_get", return_value=mock_resp):
            findings = crawl_checks("https://forbidden-robots.test")
        self.assertIsInstance(findings, list)
        self.assertTrue(
            any("403" in f["evidence"] or "Inaccessible" in f["title"]
                for f in findings)
        )

    # ------------------------------------------------------------------
    # structured-data-audit resilience
    # ------------------------------------------------------------------

    def test_structured_data_handles_malformed_json_ld(self):
        """Malformed JSON-LD must be treated as no structured data — no crash."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = """
        <html><head>
            <script type="application/ld+json">
                { "name": "Broken", invalid_key_here }
            </script>
        </head><body><h1>Test</h1></body></html>
        """
        with patch("check_structured_data.polite_get", return_value=mock_resp):
            findings = schema_checks("https://malformed-json.test")
        self.assertIsInstance(findings, list)
        self.assertTrue(
            any("Missing Machine-Readable" in f.get("title", "") for f in findings),
            "Malformed JSON-LD must produce a 'Missing Structured Data' finding",
        )

    def test_structured_data_handles_server_500(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        with patch("check_structured_data.polite_get", return_value=mock_resp):
            findings = schema_checks("https://server-500.test")
        self.assertIsInstance(findings, list)

    def test_structured_data_handles_non_ascii(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = (
            "<html><head><title>\u4e2d\u6587\u9875\u9762</title></head>"
            "<body><h1>\u4e2d\u6587\u6807\u9898</h1></body></html>"
        )
        with patch("check_structured_data.polite_get", return_value=mock_resp):
            findings = schema_checks("https://chinese-site.test")
        self.assertIsInstance(findings, list)

    # ------------------------------------------------------------------
    # freshness-corroboration resilience
    # ------------------------------------------------------------------

    def test_freshness_handles_server_500(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_resp.headers = {}
        with patch("check_freshness.polite_get", return_value=mock_resp):
            findings = freshness_checks("https://server-500.test")
        self.assertIsInstance(findings, list)

    def test_freshness_handles_network_failure(self):
        """None response must not propagate as an unhandled exception."""
        with patch("check_freshness.polite_get", return_value=None):
            findings = freshness_checks("https://unreachable.test")
        self.assertIsInstance(findings, list)

    def test_freshness_handles_completely_empty_html(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ""
        mock_resp.headers = {}
        with patch("check_freshness.polite_get", return_value=mock_resp):
            findings = freshness_checks("https://empty-page.test")
        self.assertIsInstance(findings, list)

    # ------------------------------------------------------------------
    # engagement-bounce-audit resilience
    # ------------------------------------------------------------------

    def test_engagement_handles_empty_html(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ""
        with patch("check_engagement.polite_get", return_value=mock_resp):
            findings = engagement_checks("https://empty-page.test")
        self.assertIsInstance(findings, list)

    def test_engagement_handles_none_response(self):
        with patch("check_engagement.polite_get", return_value=None):
            findings = engagement_checks("https://unreachable.test")
        self.assertIsInstance(findings, list)
        self.assertTrue(
            any("Could Not Fetch" in f["title"] for f in findings),
            "Unreachable page must produce a network-failure finding",
        )

    def test_engagement_handles_html_with_only_scripts(self):
        """Page consisting solely of <script> tags must not crash the parser."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = (
            "<html><head></head><body>"
            + "<script>var x=1;</script>" * 50
            + "</body></html>"
        )
        with patch("check_engagement.polite_get", return_value=mock_resp):
            findings = engagement_checks("https://script-only.test")
        self.assertIsInstance(findings, list)

    # ------------------------------------------------------------------
    # Orchestrator resilience
    # ------------------------------------------------------------------

    @patch("run_audit.load_skill_module")
    def test_orchestrator_contains_subskill_crashes(self, mock_load):
        mock_mod = MagicMock()
        mock_mod.run_checks.side_effect = RuntimeError("Fatal crash inside skill")
        mock_load.return_value = mock_mod

        report = run_full_audit("https://crash-test.test")
        self.assertIn("site",     report)
        self.assertIn("summary",  report)
        self.assertIn("findings", report)
        self.assertGreaterEqual(report["summary"]["total_findings"], 1)
        self.assertTrue(
            any("Notice" in f["title"] for f in report["findings"])
        )

    @patch("run_audit.load_skill_module")
    def test_orchestrator_handles_empty_findings_list(self, mock_load):
        """Skills returning empty lists must produce a valid report with zero findings."""
        mock_load.return_value = self._make_mock_module([])
        report = run_full_audit("https://clean-site.test")
        self.assertEqual(report["summary"]["total_findings"], 0)
        self.assertEqual(report["findings"], [])

    def _make_mock_module(self, findings_list):
        m = MagicMock()
        m.run_checks.return_value = findings_list
        return m


if __name__ == "__main__":
    unittest.main()
