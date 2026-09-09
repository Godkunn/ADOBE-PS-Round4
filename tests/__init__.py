"""
tests/__init__.py
Central test package configuration for brand-ai-readiness-audit.

Configures sys.path for all skill modules and shared utilities so that both
'pytest' and 'python -m unittest discover' resolve imports deterministically.
"""

from __future__ import annotations

import os
import sys
import importlib

# Ensure local test server allows localhost / 127.0.0.1 for unit/integration tests
os.environ["AUDIT_ALLOW_LOCAL_TEST"] = "1"

TESTS_DIR  = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR   = os.path.abspath(os.path.join(TESTS_DIR, ".."))
SKILLS_DIR = os.path.join(ROOT_DIR, "skills")

_SKILL_SCRIPT_DIRS = [
    os.path.join(SKILLS_DIR, "shared"),
    os.path.join(SKILLS_DIR, "crawl-render-audit",      "scripts"),
    os.path.join(SKILLS_DIR, "structured-data-audit",   "scripts"),
    os.path.join(SKILLS_DIR, "freshness-corroboration", "scripts"),
    os.path.join(SKILLS_DIR, "engagement-bounce-audit", "scripts"),
    os.path.join(SKILLS_DIR, "audit-orchestrator",       "scripts"),
]

for _d in _SKILL_SCRIPT_DIRS:
    if _d not in sys.path:
        sys.path.insert(0, _d)

_SKILL_MODULES = [
    "utils",
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
        except Exception:
            pass
