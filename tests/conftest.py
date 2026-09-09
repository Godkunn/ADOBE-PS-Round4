"""
tests/conftest.py

Centralised pytest configuration for Brand AI Readiness Audit.
Sets up sys.path for all skill modules so that tests can import them directly
and @patch() targets resolve correctly regardless of test execution order.

This file is loaded automatically by pytest before any test module is collected.
"""

from __future__ import annotations

import os
import sys
import importlib

# ---------------------------------------------------------------------------
# Absolute paths
# ---------------------------------------------------------------------------
TEST_DIR   = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR   = os.path.abspath(os.path.join(TEST_DIR, ".."))
SKILLS_DIR = os.path.join(ROOT_DIR, "skills")

_SKILL_SCRIPT_DIRS = [
    os.path.join(SKILLS_DIR, "crawl-render-audit",      "scripts"),
    os.path.join(SKILLS_DIR, "structured-data-audit",   "scripts"),
    os.path.join(SKILLS_DIR, "freshness-corroboration", "scripts"),
    os.path.join(SKILLS_DIR, "engagement-bounce-audit", "scripts"),
    os.path.join(SKILLS_DIR, "audit-orchestrator",       "scripts"),
    os.path.join(SKILLS_DIR, "shared"),
]

for _d in _SKILL_SCRIPT_DIRS:
    if _d not in sys.path:
        sys.path.insert(0, _d)

# ---------------------------------------------------------------------------
# Pre-import all skill modules so that @patch('module.requests.get') targets
# are resolved in sys.modules before any test decorator is evaluated.
# ---------------------------------------------------------------------------
_SKILL_MODULES = [
    "utils",                   # shared utils (must be first)
    "check_crawler_render",
    "check_structured_data",
    "check_freshness",
    "check_engagement",
    "run_audit",
]

for _mod_name in _SKILL_MODULES:
    if _mod_name not in sys.modules:
        try:
            importlib.import_module(_mod_name)
        except Exception:  # noqa: BLE001 — graceful failure if a dep is missing
            pass
