---
name: structured-data-audit
description: Audits web pages for Schema.org JSON-LD structured data, validating Product, Offer, Organization, and FAQPage schemas, and checking entity disambiguation.
license: Apache-2.0
metadata:
  version: 1.0.0
  author: AI Engineering Team
  category: structured-data
  tags:
    - schema
    - json-ld
    - microdata
    - entity-resolution
    - product-schema
---

# Structured Data & Schema Audit

## When to use
Use this skill to evaluate whether Generative AI search engines and RAG pipelines can extract unambiguous, authoritative facts (such as product specs, prices, stock availability, brand identity, and FAQs) directly from machine-readable Schema.org JSON-LD markup.

## Inputs
- `url`: (string, required) Target webpage URL to inspect.
- `--timeout`: (integer, optional) Per-request timeout in seconds (default: 10).

## Procedure
1. **Fetch & Parse HTML:** Retrieve the target page's raw HTML and extract all `<script type="application/ld+json">` tags.
2. **JSON-LD Syntax & Extraction:** Safely parse each JSON block, unwrapping single objects, arrays, and nested `@graph` structures.
3. **Core Schema Existence Check:**
   - Detect whether any JSON-LD exists. If absent, flag high-severity gap.
   - Catalog all `@type` definitions present across the document.
4. **Product & Offer Schema Validation:**
   - Detect if page is product/catalog focused (presence of cart, pricing, buy keywords).
   - Validate existence of `Product` and `Offer` schemas.
   - Check mandatory attributes: `name`, `description`, `image`, and nested `offers` (`price`, `priceCurrency`, `availability`).
5. **Entity Disambiguation & Knowledge Graph (`sameAs`):**
   - Check `Organization` or `Brand` schemas for `sameAs` authority links (Wikidata, Wikipedia, LinkedIn, X, Crunchbase).
6. **FAQPage Verification:**
   - Detect presence of Q&A patterns in DOM without corresponding `FAQPage` schema.
7. **Findings Generation:** Emit standardized findings objects with severity ratings and specific remediation instructions.

## Output
Returns a JSON array of findings:

```json
[
  {
    "title": "Missing Machine-Readable Structured Data (JSON-LD)",
    "severity": "high",
    "evidence": "Found 0 valid <script type='application/ld+json'> blocks on the page. AI search crawlers cannot deterministically extract entities or facts.",
    "suggested_action": {
      "summary": "Implement Schema.org JSON-LD markup defining core Organization, Product, WebPage, and Article entities.",
      "priority": "high"
    }
  }
]
```
