---
name: audit-orchestrator
description: Entrypoint orchestrator skill that coordinates all auditing sub-skills, aggregates findings, and produces a strictly formatted JSON report.
license: Apache-2.0
metadata:
  version: 1.0.0
  author: AI Engineering Team
  category: orchestration
  tags:
    - audit
    - orchestrator
    - geo
    - ai-readiness
---

# Audit Orchestrator

## When to use
Use this skill as the primary entrypoint to audit any brand or website URL for Generative Engine Optimization (GEO) and on-site AI engagement readiness. It automates the execution of all four specialized auditing sub-skills and aggregates their findings into a single, standardized JSON audit report.

## Inputs
- `url`: (string, required) Target website URL or hostname (e.g. `https://example.com` or `example.com`).
- `--output`: (string, optional) File path to persist the generated JSON report.
- `--timeout`: (integer, optional) Per-request timeout in seconds (default: 10).

## Procedure
1. **Target Normalization:** Normalize the input URL to validate the scheme and extract the target hostname.
2. **Sub-Skill Coordination:**
   - Execute `crawl-render-audit` (`check_crawler_render.py`): evaluates `robots.txt`, AI bot permissions, and JS rendering dependencies.
   - Execute `structured-data-audit` (`check_structured_data.py`): inspects JSON-LD schemas (`Product`, `Offer`, `Organization`, `FAQPage`, `sameAs`).
   - Execute `freshness-corroboration` (`check_freshness.py`): verifies temporal metadata, sitemap `<lastmod>`, and copyright freshness.
   - Execute `engagement-bounce-audit` (`check_engagement.py`): evaluates above-the-fold direct answers, anchor IDs, and popups.
3. **Aggregation & Normalization:**
   - Merge all raw findings from the 4 sub-skills.
   - Assign deterministic sequential identifiers: `F-001`, `F-002`, `F-003`, etc.
   - Compute severity metrics: `total_findings`, `critical`, `high`, `medium`.
4. **Report Generation:** Serialize output strictly matching the required JSON schema and emit to standard output.

## Output
Strictly formatted JSON report object:

```json
{
  "site": "https://example.com",
  "audited_at": "2026-08-28T12:00:00Z",
  "summary": {
    "total_findings": 3,
    "critical": 1,
    "high": 1,
    "medium": 1
  },
  "findings": [
    {
      "id": "F-001",
      "title": "AI Web Crawlers Blocked in robots.txt",
      "severity": "critical",
      "evidence": "robots.txt explicitly disallows User-agent: GPTBot from root path (/)",
      "suggested_action": {
        "summary": "Update robots.txt to explicitly allow GPTBot, PerplexityBot, and ClaudeBot to crawl public catalog directories.",
        "priority": "high"
      }
    }
  ]
}
```
