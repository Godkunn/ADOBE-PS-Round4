---
name: engagement-bounce-audit
description: Audits on-site engagement friction, direct-answer layout above the fold, deep-link anchor IDs, and intrusive modals that cause AI-referred visitors to bounce.
license: Apache-2.0
metadata:
  version: 1.0.0
  author: AI Engineering Team
  category: user-engagement
  tags:
    - engagement
    - bounce-rate
    - direct-answer
    - anchor-links
    - modals
---

# Engagement & Bounce Audit

## When to use
Use this skill when auditing how well a landing page retains visitors arriving from Generative AI search engines (ChatGPT, Perplexity). AI search users expect immediate answers matching their conversational query; pages that bury answers or block view with modals create friction and high bounce rates.

## Inputs
- `url`: (string, required) Target webpage URL to inspect.
- `--timeout`: (integer, optional) Per-request timeout in seconds (default: 10).

## Procedure
1. **Direct Answer First Layout:**
   - Locate primary `<h1>` element.
   - Inspect the subsequent sibling elements in the top 20% of the DOM.
   - Check whether a concise explanatory paragraph or summary card (< 80 words) provides immediate context above the fold.
2. **Deep-Link Anchor Verification:**
   - Scan `<h2>`, `<h3>`, `<section>`, and `<article>` tags for HTML `id` attributes.
   - Verify if AI engines can generate deep citations pointing to specific subsections (e.g., `#features`, `#pricing`).
3. **Intrusive Modals & Interstitials:**
   - Check DOM for elements with classes or IDs indicative of full-screen overlays, newsletter popups, or lead gates intercepting immediate reading.
4. **Text-to-HTML Ratio Assessment:**
   - Measure visible text character volume against total HTML document weight to flag DOM bloat.
5. **Findings Emission:** Compile standardized findings with remediation guidance.

## Output
Returns a JSON array of findings:

```json
[
  {
    "title": "Buried Direct Answer Above The Fold (High Bounce Risk)",
    "severity": "medium",
    "evidence": "H1 heading is not followed by an immediate concise summary paragraph (<80 words) above the fold.",
    "suggested_action": {
      "summary": "Place a 2-3 sentence executive answer or summary callout directly underneath the main H1 heading.",
      "priority": "medium"
    }
  }
]
```
