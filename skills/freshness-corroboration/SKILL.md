---
name: freshness-corroboration
description: Audits publication/update timestamps, sitemap lastmod tags, canonical tags, and copyright freshness to prevent stale AI knowledge synthesis.
license: Apache-2.0
metadata:
  version: 1.0.0
  author: AI Engineering Team
  category: temporal-freshness
  tags:
    - freshness
    - lastmod
    - sitemap
    - canonical
    - timestamps
---

# Freshness & Corroboration Audit

## When to use
Use this skill when auditing whether a website provides clear, machine-verifiable temporal freshness signals and authoritative canonical citations. LLM search engines rely on these signals to prevent hallucinations, avoid quoting outdated facts (prices, policies, features), and confirm content recency.

## Inputs
- `url`: (string, required) Target webpage URL to inspect.
- `--timeout`: (integer, optional) Per-request timeout in seconds (default: 10).

## Procedure
1. **Temporal Meta Tag Extraction:**
   - Inspect `<head>` for `<meta property="article:modified_time">`, `<meta property="og:updated_time">`, `<meta name="last-modified">`, `<meta name="date">`, and `<time datetime="...">` elements.
   - Inspect HTTP response headers for `Last-Modified` and `Date`.
2. **Sitemap XML Inspection:**
   - Query `/sitemap.xml` on the target origin.
   - Parse XML elements to verify presence of `<lastmod>` timestamps in W3C/ISO-8601 format.
3. **Stale Copyright & Legacy Footprint Detection:**
   - Scan page `<footer>` and bottom DOM regions for copyright statements.
   - Extract declared years and flag instances older than current operational years (< 2025).
4. **Canonical Link Validation:**
   - Verify existence and format of `<link rel="canonical" href="...">` tags.
5. **Findings Emission:** Compile findings according to the standardized schema.

## Output
Returns a JSON array of findings:

```json
[
  {
    "title": "Missing Temporal & Freshness Metadata",
    "severity": "medium",
    "evidence": "Page lacks 'article:modified_time', 'og:updated_time', or HTTP Last-Modified headers. Generative AI engines cannot verify content recency and risk treating facts as stale.",
    "suggested_action": {
      "summary": "Publish machine-readable ISO-8601 timestamps in OpenGraph and Schema.org 'dateModified' metadata on all dynamic and catalog pages.",
      "priority": "medium"
    }
  }
]
```
