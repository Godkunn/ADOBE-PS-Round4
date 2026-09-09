---
name: crawl-render-audit
description: Audits website accessibility for AI web crawlers in robots.txt, detects WAF bot blocking, and evaluates client-side JavaScript rendering (CSR) dependencies.
license: Apache-2.0
metadata:
  version: 1.0.0
  author: AI Engineering Team
  category: crawler-accessibility
  tags:
    - robots.txt
    - crawlers
    - gptbot
    - javascript-rendering
    - csr
---

# Crawl & Render Audit

## When to use
Use this skill when evaluating whether Generative AI search crawlers (e.g., GPTBot, PerplexityBot, ClaudeBot, Google-Extended) can access, fetch, and read a target website without being blocked by `robots.txt`, WAF security rules, or heavy client-side JavaScript execution requirements.

## Inputs
- `url`: (string, required) The target website URL or domain (e.g., `https://example.com` or `example.com`).
- `--timeout`: (integer, optional) Per-request timeout in seconds (default: 10).

## Procedure
1. **Target Normalization:** Normalize the input URL to ensure a proper HTTP/HTTPS scheme and resolve the root domain.
2. **Robots.txt Analysis:**
   - Fetch the root `/robots.txt` resource.
   - Parse `User-agent` directives, checking specifically for known AI crawlers: `GPTBot`, `PerplexityBot`, `ClaudeBot`, `Google-Extended`, `Amazonbot`, `CCBot`, `Bytespider`, `Applebot-Extended`, and wildcard `*`.
   - Identify `Disallow` rules blocking root (`/`) or critical catalog/content paths.
3. **AI User-Agent WAF Probe:**
   - Issue a lightweight GET request mimicking an official AI crawler (`GPTBot/1.2`).
   - Flag 403 Forbidden, 401 Unauthorized, or 429 Too Many Requests responses indicative of CDN/WAF bot-blocking.
4. **Client-Side Rendering (CSR) vs Static HTML Assessment:**
   - Fetch raw static HTML using standard browser headers.
   - Check for empty SPA root containers (`<div id="root">`, `<div id="app">`, `<div id="__next">`).
   - Calculate static body word count vs total `<script>` payload size. If raw words < 150 while script size > 50KB, flag heavy CSR dependency.
5. **Findings Formulation:** Generate structured finding objects matching the standardized schema.

## Output
Returns a JSON array of finding objects:

```json
[
  {
    "title": "AI Web Crawlers Blocked in robots.txt",
    "severity": "critical",
    "evidence": "robots.txt at https://example.com/robots.txt disallows root path (/) for AI agents: GPTBot, PerplexityBot.",
    "suggested_action": {
      "summary": "Update robots.txt to explicitly allow AI search crawlers (GPTBot, PerplexityBot, ClaudeBot, Google-Extended) to index public product and content routes.",
      "priority": "high"
    }
  }
]
```
