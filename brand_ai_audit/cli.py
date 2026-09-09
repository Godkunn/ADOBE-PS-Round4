#!/usr/bin/env python3
"""
brand_ai_audit/cli.py

Proper CLI entry point package for 'pip install .' / 'brand-ai-audit' console script.
Bridges the pyproject.toml [project.scripts] entry point to the dynamic-loaded
orchestrator without requiring hyphenated directory names to be Python packages.
"""

from __future__ import annotations

import os
import sys


def _ensure_orchestrator_on_path() -> None:
    """Add the orchestrator scripts directory to sys.path if not already present."""
    # 1. Try resolving via imported skills package (works in site-packages/wheels)
    try:
        import skills  # type: ignore[import]
        skills_root = os.path.dirname(os.path.abspath(skills.__file__))
        orch_scripts = os.path.join(skills_root, "audit-orchestrator", "scripts")
        if os.path.isdir(orch_scripts) and orch_scripts not in sys.path:
            sys.path.insert(0, orch_scripts)
            return
    except Exception:
        pass

    # 2. Fallback to source repo hierarchy: <repo>/skills/audit-orchestrator/scripts/
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    orch_scripts = os.path.join(repo_root, "skills", "audit-orchestrator", "scripts")
    if orch_scripts not in sys.path:
        sys.path.insert(0, orch_scripts)


def main() -> None:
    """Console-script entry point: delegates to run_audit.main()."""
    _ensure_orchestrator_on_path()
    # pylint: disable=import-outside-toplevel
    from run_audit import main as _main  # type: ignore[import]
    _main()


if __name__ == "__main__":  # pragma: no cover
    main()
