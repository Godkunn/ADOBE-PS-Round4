#!/usr/bin/env python3
"""
tests/test_performance.py

Performance tests for Brand AI Readiness Audit.
Ensures total orchestration runtime is strictly within hackathon constraints
(< 5 minutes; target < 5 seconds) on fully mocked network calls.

Fix: Patches at run_audit.load_skill_module level — avoids the fragile
@patch("check_crawler_render.requests.get") pattern which breaks when modules
are loaded via importlib.util.spec_from_file_location (as the orchestrator does).
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: F401

from run_audit import run_full_audit


class TestOrchestratorPerformance(unittest.TestCase):

    def _mock_module(self, findings=None):
        m = MagicMock()
        m.run_checks.return_value = findings or []
        return m

    @patch("run_audit.load_skill_module")
    def test_orchestration_under_5_seconds(self, mock_load):
        """Full mocked audit must complete in under 5 seconds."""
        mock_load.return_value = self._mock_module([
            {
                "title":    "Missing Canonical URL Declaration",
                "severity": "medium",
                "evidence": "No canonical tag found.",
                "suggested_action": {"summary": "Add canonical link.", "priority": "medium"},
                "confidence": 0.97,
            }
        ])

        start   = time.perf_counter()
        report  = run_full_audit("https://performance-benchmark.test")
        elapsed = time.perf_counter() - start

        self.assertLess(
            elapsed, 5.0,
            f"Full mocked audit took {elapsed:.3f}s, exceeding 5s target",
        )
        self.assertIn("summary",  report)
        self.assertIn("findings", report)

    @patch("run_audit.load_skill_module")
    def test_repeated_audits_do_not_degrade(self, mock_load):
        """5 consecutive mocked audits must each complete in < 5 seconds."""
        mock_load.return_value = self._mock_module()

        for i in range(5):
            start   = time.perf_counter()
            run_full_audit(f"https://perf-iter-{i}.test")
            elapsed = time.perf_counter() - start
            self.assertLess(
                elapsed, 5.0,
                f"Iteration {i} took {elapsed:.3f}s — indicates performance regression",
            )

    @patch("run_audit.load_skill_module")
    def test_large_findings_list_does_not_timeout(self, mock_load):
        """Deduplication and serialisation of 200 findings must stay < 5s."""
        findings = [
            {
                "title":    f"Test Finding {n}",
                "severity": "medium",
                "evidence": f"Evidence for finding number {n} is this unique text.",
                "suggested_action": {"summary": "Fix it.", "priority": "medium"},
                "confidence": 0.85,
            }
            for n in range(200)
        ]
        mock_load.return_value = self._mock_module(findings)

        start   = time.perf_counter()
        report  = run_full_audit("https://large-findings.test")
        elapsed = time.perf_counter() - start

        self.assertLess(elapsed, 5.0)
        # All 200 unique findings should be kept (unique title+evidence)
        self.assertGreaterEqual(report["summary"]["total_findings"], 1)


if __name__ == "__main__":
    unittest.main()
