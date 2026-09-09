# TEST_INFRA.md — Testing Infrastructure & Quality Assurance

## 1. Overview

The test infrastructure for `brand-ai-readiness-audit` provides comprehensive automated verification of:
1. **Marketplace & Standard Compliance**: Validating `marketplace.json` schema, single entrypoint constraints, and all `SKILL.md` YAML frontmatters and required sections.
2. **Sub-Skill Heuristic Execution**: Unit and mock tests for all 4 sub-skills across various website scenarios (clean sites, blocked bots, CSR apps, missing schemas, stale timestamps, popup overlays).
3. **Orchestrator End-to-End**: Validating CLI parsing, sub-skill invocation, finding deduplication, severity sorting, sequential ID generation, and strict JSON output compliance.
4. **Resiliency & Edge Cases**: Testing network timeouts, DNS errors, HTTP 403 WAF blocks, malformed HTML, and invalid JSON-LD.

---

## 2. Test Suites & Layout

```
brand-ai-readiness-audit/
├── tests/
│   ├── __init__.py                   # Package initialization
│   ├── bootstrap.py                  # Universal sys.path bootstrap
│   ├── conftest.py                   # Pytest fixtures and pre-imports
│   ├── mock_server.py                # Local threaded HTTP mock server
│   ├── test_marketplace.py           # Validates marketplace.json and SKILL.md specs
│   ├── test_skills.py                # Sub-skill heuristics and orchestrator integration
│   ├── test_resilience.py            # Timeouts, 500s, malformed HTML, and edge cases
│   ├── test_performance.py           # Execution benchmarking under 5 seconds
│   └── test_bug_fixes.py             # Security hardening, SSRF regression & edge case tests
```

---

## 3. Test Execution Commands

### Running all tests (98 tests, 100% passing):
```bash
python -m unittest discover -s tests -p "test_*.py"
```

### Running individual test suites:
```bash
# Validate marketplace manifest & SKILL.md files (agentskills.io compliance)
python -m unittest tests/test_marketplace.py

# Test sub-skill heuristics, mock server scenarios & orchestrator integration
python -m unittest tests/test_skills.py

# Test resilience, timeout handling, crash containment & SSRF protection
python -m unittest tests/test_resilience.py

# Test execution performance (< 5s runtime budget)
python -m unittest tests/test_performance.py

# Test security hardening, SSRF vectors, and bug regressions
python -m unittest tests/test_bug_fixes.py
```

---

## 4. Test Verification Checks

| Test Category | Target Check | Pass Condition |
| :--- | :--- | :--- |
| **Manifest Integrity** | `marketplace.json` | Valid JSON, exactly 5 skills, exactly 1 `entrypoint: true` (`audit-orchestrator`), all paths valid |
| **SKILL.md Spec** | All `SKILL.md` | Valid YAML frontmatter with `name`, `description`, `license: Apache-2.0`, and all 4 Markdown sections (`## When to use`, `## Inputs`, `## Procedure`, `## Output`) |
| **Deterministic JSON** | `run_audit.py` stdout | Matches exact report schema (`site`, `audited_at`, `summary`, `findings`), IDs match `^F-\d{3,}$` |
| **Error Handling** | Unreachable / timeout URLs | Sub-skills catch exceptions, return `[]`, orchestrator returns valid JSON with 0 findings without crash |
