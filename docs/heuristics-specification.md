# Heuristics & Scoring Engine Specification

## 1. Overview
This document specifies the exact mathematical formulas, threshold values, and deterministic heuristic evaluation rules implemented across the Brand AI-Readiness Audit Marketplace.

---

## 2. Heuristic Rules & Thresholds

### 2.1. Pillar 1: Off-Site AI Discoverability

#### Rule 1.1: AI Crawler Accessibility (`crawl-render-audit`)
* **Target:** `/robots.txt`
* **Evaluated AI User-Agents:** `GPTBot`, `ChatGPT-User`, `PerplexityBot`, `ClaudeBot`, `Claude-Web`, `Google-Extended`, `Amazonbot`, `CCBot`, `anthropic-ai`, `cohere-ai`, `Bytespider`, `Applebot-Extended`.
* **Heuristic:**
  $$\text{BlockedBots} = \{ b \in \text{AIBots} \mid \text{Disallows}(b) \cap \{'/', '/*', '/products', '/catalog', '/shop', '/blog'\} \neq \emptyset \}$$
  $$\text{WildcardBlocked} = ('/' \in \text{Disallows}('*')) \lor ('/*' \in \text{Disallows}('*'))$$
* **Severity:**
  * If $\text{BlockedBots} \neq \emptyset \lor \text{WildcardBlocked} \implies \mathbf{critical}$

#### Rule 1.2: Client-Side Rendering vs SSR Dependency (`crawl-render-audit`)
* **Target:** Target Webpage Static HTML
* **Heuristic:**
  $$\text{HasEmptySPAContainer} = (\exists \text{ node} \in \{\text{#root, #app, #__next, #___gatsby}\} \text{ with } \text{WordCount}(\text{node}) < 40)$$
  $$\text{CSRFlag} = (\text{HasEmptySPAContainer} \land \text{ScriptPayloadBytes} > 50{,}000) \lor (\text{TotalBodyWords} < 150)$$
* **Severity:**
  * If $\text{CSRFlag} = \text{True} \implies \mathbf{high}$

#### Rule 1.3: Machine-Readable Schema.org Structured Data (`structured-data-audit`)
* **Target:** `<script type="application/ld+json">`
* **Heuristic:**
  * If $\text{Count}(\text{ValidJSONLD}) = 0 \implies \mathbf{high}$
  * If $\text{IsProductPage} \land \text{ProductSchemaMissing} \implies \mathbf{high}$
  * If $\text{HasProductSchema} \land (\neg\text{has}(price) \lor \neg\text{has}(priceCurrency) \lor \neg\text{has}(availability)) \implies \mathbf{medium}$
  * If $\text{OrganizationSchemaMissing} \implies \mathbf{medium}$
  * If $\text{HasOrganizationSchema} \land \text{len}(sameAs) = 0 \implies \mathbf{medium}$
  * If $\text{HasFAQContentInDOM} \land \text{FAQPageSchemaMissing} \implies \mathbf{medium}$

#### Rule 1.4: Freshness & Temporal Metadata (`freshness-corroboration`)
* **Target:** `<head>` metadata, HTTP headers, `/sitemap.xml`
* **Heuristic:**
  * If $\neg\text{has}(dateModified) \land \neg\text{has}(article:modified\_time) \land \neg\text{has}(Last\text{-}Modified) \implies \mathbf{medium}$
  * If $\forall u \in \text{SitemapSample}, (\text{CurrentDate} - lastmod(u) > 365 \text{ days}) \implies \mathbf{medium}$
  * If $\max(\text{FooterCopyrightYears}) < (\text{CurrentYear} - 1) \implies \mathbf{medium}$
  * If $\neg\text{has}(rel=\text{"canonical"}) \implies \mathbf{medium}$

---

### 2.2. Pillar 2: On-Site Engagement & Context Retention

#### Rule 2.1: Direct Answer First Layout (`engagement-bounce-audit`)
* **Target:** Top 20% DOM / Heading Sibling Nodes
* **Heuristic:**
  * If $\neg\text{has}(h1) \implies \mathbf{medium}$
  * If $\text{has}(h1) \land \neg\exists p \text{ in immediate siblings with } (8 \le \text{WordCount}(p) \le 80) \implies \mathbf{medium}$

#### Rule 2.2: Deep-Link Citation Anchors (`engagement-bounce-audit`)
* **Target:** `<section>`, `<article>`, `<h2>`, `<h3>`
* **Heuristic:**
  $$\text{AnchorRatio} = \frac{|\{ s \in \text{MajorSections} \mid \text{hasAttr}(s, 'id') \}|}{|\text{MajorSections}|}$$
  * If $|\text{MajorSections}| \ge 3 \land \text{AnchorRatio} < 0.35 \implies \mathbf{medium}$

#### Rule 2.3: Intrusive Interstitials & Modal Overlays (`engagement-bounce-audit`)
* **Target:** DOM class/ID names matching `modal|popup|newsletter-signup|overlay|lightbox|subscribe-dialog|intercom-frame`
* **Severity:**
  * If blocking modal elements detected on initial load $\implies \mathbf{medium}$

#### Rule 2.4: Text-to-HTML Code Ratio (`engagement-bounce-audit`)
* **Target:** Visible text characters vs total HTML payload
* **Heuristic:**
  $$\text{TextRatio} = \frac{\text{Len}(\text{VisibleTextChars})}{\text{Len}(\text{TotalHTMLChars})} \times 100\%$$
  * If $\text{TotalHTMLBytes} > 15{,}000 \land \text{TextRatio} < 6.0\% \implies \mathbf{medium}$

---

## 3. Severity & Prioritization Matrix

| Finding Code | Severity | Action Priority | Rationale |
|---|---|---|---|
| AI Bots Blocked in robots.txt | `critical` | `high` | Complete exclusion from AI crawler index |
| WAF / Bot Block (401/403/429) | `critical` | `high` | Edge security terminates connection before parsing |
| Content Hidden by CSR | `high` | `high` | LLM scrapers cannot execute JavaScript |
| Missing JSON-LD Structured Data | `high` | `high` | Absence of machine-readable entity definitions |
| Missing Product/Offer Schema | `high` | `high` | Product specifications/pricing unavailable to RAG |
| Incomplete Product Offers | `medium` | `high`/`medium` | Incomplete pricing or stock data prevents citation |
| Missing Entity sameAs Links | `medium` | `medium` | Risk of AI knowledge graph hallucination |
| Missing Temporal Metadata | `medium` | `medium` | AI engines treat facts as potentially stale |
| Stale Sitemap lastmod | `medium` | `low` | Crawlers fail to prioritize updated URLs |
| Outdated Copyright Year | `medium` | `low` | Signals neglected brand presence |
| Missing Canonical URL | `medium` | `medium` | Inconsistent citation URLs across search engines |
| Buried Direct Answer | `medium` | `medium` | AI referral users face high cognitive friction |
| Missing Deep Anchors | `medium` | `medium` | AI assistants cannot link directly to specific answers |
| Intrusive Modal Overlays | `medium` | `medium` | Interstitials increase bounce rate on arrival |
| Low Text-to-HTML Ratio | `medium` | `low` | Code bloat slows crawler token ingestion |
