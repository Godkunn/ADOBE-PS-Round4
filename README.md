# Brand AI Readiness Audit — Agent Skill Marketplace

An enterprise-grade, modular **Agent Skill Marketplace** built according to the [agentskills.io](https://agentskills.io) specification for autonomous AI agent systems and the Adobe Hackathon Round 3 problem statement.

This package enables an AI agent to execute non-destructive, read-only audits on any target website domain/URL to identify **AI Discoverability** (Generative Engine Optimization / GEO) and **On-Site Engagement** gaps, producing a deterministic, strictly formatted JSON audit report.

---

## 1. Context & Domain Knowledge (GEO vs SEO)

Traditional SEO optimizes for SERP link indexing. Generative AI engines (such as **ChatGPT Search**, **Perplexity**, **Google Gemini**, and **Microsoft Copilot**) rely on Retrieval-Augmented Generation (RAG) pipelines that directly retrieve, corroborate, and synthesize facts into paragraph answers.

Websites encounter two core failure modes when interacting with generative search engines:
1. **Off-site AI Discoverability Fails:** AI web scrapers are blocked via `robots.txt` or WAF policies, core content is trapped behind client-side JavaScript rendering (CSR) invisible to non-JS scrapers, or structured data (JSON-LD Schema.org) is missing/incomplete.
2. **On-site Engagement & Context Fails:** Arrived visitors referred by an AI summary bounce immediately because the landing page lacks context retention, hides direct answers behind intrusive modals or below the fold, or lacks deep-link anchor IDs for precise citations.

---

## 2. Marketplace Architecture & Composition

The package follows strict separation of concerns, decomposing the audit lifecycle into five isolated, modular skills. Exactly one skill (`audit-orchestrator`) is designated as the entrypoint.

```
brand-ai-readiness-audit/
├── marketplace.json                 # Root manifest registering all 5 skills
├── README.md                        # Repository documentation
├── requirements.txt                 # Python dependencies: requests, beautifulsoup4
├── pyproject.toml                   # Modern PEP 621 packaging specification
├── PROJECT.md                       # Architecture, layout, and scoring specifications
├── TEST_INFRA.md                    # Hermetic test harness & mock server documentation
├── TEST_READY.md                    # Validation & readiness certificate
├── SECURITY.md                      # Passive auditing & zero-PII security policy
├── Makefile                         # Developer automation (make test, make audit, make pack)
├── Dockerfile                       # Production multi-stage container
├── docker-compose.yml               # Containerised execution config
├── package_verify.py                # Single-click packager & isolated sandbox verification tool
├── sample_audit_report.json         # Verified canonical audit output sample
├── benchmarks/
│   ├── benchmark_results.json       # Empirical GEO audit of 512 real domains across 8 sectors
│   ├── benchmark_executive_report.html # Interactive visual explorer & scorecard for 512 domains
│   └── run_live_benchmark_500.py    # Multi-threaded batch runner for empirical validation
├── .gitignore                       # Standard ignore rules
├── brand_ai_audit/                  # Python distribution bridge package
│   ├── __init__.py
│   └── cli.py                       # CLI entrypoint for 'pip install .'
├── docs/
│   ├── architecture.md              # System architecture & GEO retrieval mechanics
│   ├── heuristics-specification.md  # Formal algorithms & severity matrix
│   ├── operational-runbook.md       # SRE deployment & troubleshooting runbook
│   └── dashboard.html               # Visual reporting UI
├── tests/
│   ├── __init__.py
│   ├── bootstrap.py                 # Universal sys.path resolver
│   ├── conftest.py                  # Pytest fixtures and mock setups
│   ├── mock_server.py               # Zero-dependency local mock HTTP test server
│   ├── test_marketplace.py          # agentskills.io specification compliance tests
│   ├── test_skills.py               # Core skill unit & integration tests
│   ├── test_resilience.py           # Adversarial & network failure tests
│   └── test_performance.py          # Latency benchmark tests
└── skills/
    ├── audit-orchestrator/          # [ENTRYPOINT] Dynamic loader & JSON serializer
    │   ├── SKILL.md
    │   └── scripts/run_audit.py
    ├── crawl-render-audit/          # 12 AI bots + CSR vs SSR + Turnstile/Anti-Bot detection
    │   ├── SKILL.md
    │   └── scripts/
    │       ├── check_crawler_render.py
    │       └── check_render.py
    ├── structured-data-audit/       # Schema.org JSON-LD entity & sameAs validation
    │   ├── SKILL.md
    │   └── scripts/
    │       ├── check_structured_data.py
    │       └── check_schema.py
    ├── freshness-corroboration/     # Temporal signals, sitemap staleness & HSTS transport
    │   ├── SKILL.md
    │   └── scripts/check_freshness.py
    └── engagement-bounce-audit/     # Direct answers, anchors, ad/tracker bloat & cookie walls
        ├── SKILL.md
        └── scripts/check_engagement.py
```

### Manifest Definition (`marketplace.json`)
```json
{
  "name": "brand-ai-readiness-audit",
  "version": "1.0.0",
  "description": "Enterprise Agent Skill Marketplace for automated AI Discoverability (GEO) and On-Site Engagement auditing.",
  "license": "Apache-2.0",
  "author": "AI Engineering Team",
  "entrypoint": "skills/audit-orchestrator",
  "skills": [
    {
      "id": "audit-orchestrator",
      "name": "audit-orchestrator",
      "path": "skills/audit-orchestrator",
      "entrypoint": true
    },
    {
      "id": "crawl-render-audit",
      "name": "crawl-render-audit",
      "path": "skills/crawl-render-audit"
    },
    {
      "id": "structured-data-audit",
      "name": "structured-data-audit",
      "path": "skills/structured-data-audit"
    },
    {
      "id": "freshness-corroboration",
      "name": "freshness-corroboration",
      "path": "skills/freshness-corroboration"
    },
    {
      "id": "engagement-bounce-audit",
      "name": "engagement-bounce-audit",
      "path": "skills/engagement-bounce-audit"
    }
  ]
}
```

---

## 3. Modular Skill Breakdown & Heuristics

| Skill ID | Primary Script | Core Auditing Responsibility & Heuristics |
|---|---|---|
| `audit-orchestrator` | `run_audit.py` | **Entrypoint**: Dynamically loads sub-skills, aggregates findings, deduplicates by title, assigns sequential IDs (`F-001`...), calculates severity counts, outputs final JSON schema. |
| `crawl-render-audit` | `check_crawler_render.py` | Verifies `robots.txt` for 12 AI crawler user-agents (`GPTBot`, `PerplexityBot`, `ClaudeBot`, `Google-Extended`, etc.), evaluates static HTML vs client-side JS dependency (CSR), checks WAF bot status codes (401/403/429), and diagnoses Anti-Bot challenges (Turnstile, reCAPTCHA, DataDome). |
| `structured-data-audit` | `check_structured_data.py` | Extracts `<script type="application/ld+json">`, validates Schema types (`Product`, `Offer`, `Organization`, `FAQPage`, `Article`), verifies pricing/currency coverage, and checks `sameAs` entity disambiguation. |
| `freshness-corroboration` | `check_freshness.py` | Audits temporal meta tags (`dateModified`, `article:modified_time`), inspects `sitemap.xml` `<lastmod>` timestamps for presence and staleness (>12 months), checks footer copyright freshness, validates canonical link integrity, and evaluates HSTS transport health. |
| `engagement-bounce-audit` | `check_engagement.py` | Analyzes Direct Answer First layout in top 20% DOM (<80 words following H1), checks for deep-link citation anchors (`#id`), inspects intrusive modal overlays/popups, measures text-to-HTML ratio, and detects heavy ad/tracker bloat & cookie walls. |

---

## 4. Setup & Prerequisites

All scripts require **Python 3.8+** and use only lightweight, standard networking and parsing libraries. No paid API keys (OpenAI/Gemini/etc.) are required.

```bash
# Install required dependencies
pip install -r requirements.txt
```

---

## 5. Execution Instructions

### A. Run Full Audit via Entrypoint Orchestrator
To execute the complete multi-skill audit against any website:

```bash
# Basic usage (outputs JSON to stdout)
python skills/audit-orchestrator/scripts/run_audit.py https://example.com

# Save report directly to a file
python skills/audit-orchestrator/scripts/run_audit.py https://example.com --output report.json

# Using CLI flag syntax with custom timeout
python skills/audit-orchestrator/scripts/run_audit.py --url https://example.com --timeout 15
```

### B. Run Sub-Skills Individually
Each skill is completely decoupled and can be invoked independently:

```bash
# 1. Crawl & Render Audit
python skills/crawl-render-audit/scripts/check_crawler_render.py https://example.com

# 2. Structured Data Audit
python skills/structured-data-audit/scripts/check_structured_data.py https://example.com

# 3. Freshness & Corroboration Audit
python skills/freshness-corroboration/scripts/check_freshness.py https://example.com

# 4. Engagement & Bounce Audit
python skills/engagement-bounce-audit/scripts/check_engagement.py https://example.com
```

### C. Run Automated Test Suite
```bash
# Discover and run all 62 automated tests (unit, manifest, resilience, performance)
python -m unittest discover -s tests

# Or using Makefile
make test
```

---

## 6. Output JSON Schema Specification

The entrypoint orchestrator emits deterministic JSON adhering strictly to this schema:

```json
{
  "site": "https://example.com",
  "audited_at": "2026-08-28T10:20:42Z",
  "summary": {
    "total_findings": 4,
    "critical": 0,
    "high": 2,
    "medium": 2
  },
  "findings": [
    {
      "id": "F-001",
      "title": "Content Hidden Behind Client-Side JavaScript (CSR)",
      "severity": "high",
      "evidence": "Raw server-rendered HTML contains only 21 visible words, with 0 script tags (0.0 KB inline JS). AI crawlers that do not execute JavaScript will see a near-empty page.",
      "suggested_action": {
        "summary": "Adopt Server-Side Rendering (SSR) or Static Site Generation (SSG) for key entity/product pages so facts exist in the raw HTML response.",
        "priority": "high"
      }
    },
    {
      "id": "F-002",
      "title": "Missing Machine-Readable Structured Data (JSON-LD)",
      "severity": "high",
      "evidence": "Found 0 valid <script type='application/ld+json'> blocks on https://example.com. AI search crawlers cannot deterministically extract entities or facts.",
      "suggested_action": {
        "summary": "Add Schema.org JSON-LD markup (Organization at minimum, plus Product/FAQPage/Article where relevant) so AI engines can extract unambiguous facts.",
        "priority": "high"
      }
    },
    {
      "id": "F-003",
      "title": "Missing Canonical URL Declaration",
      "severity": "medium",
      "evidence": "Page does not declare a `<link rel='canonical'>` tag. Inconsistent URLs may cause conflicting knowledge citations across AI engines.",
      "suggested_action": {
        "summary": "Add a self-referential `<link rel='canonical' href='https://...'>` in `<head>` to establish single-source-of-truth URL indexing.",
        "priority": "medium"
      }
    },
    {
      "id": "F-004",
      "title": "Sitemap Missing or Invalid",
      "severity": "medium",
      "evidence": "https://example.com/sitemap.xml returned HTTP 404 or is not a valid XML sitemap.",
      "suggested_action": {
        "summary": "Publish a valid sitemap.xml at the domain root and reference it in robots.txt.",
        "priority": "medium"
      }
    }
  ]
}
```

---

## 7. Operational Constraints Met
- **Recommend-Only**: 100% passive, read-only GET requests. Never mutates or affects target websites.
- **No External / Paid APIs**: Pure heuristic parsing with `requests` + `beautifulsoup4`, regex, and `json`.
- **Fast Execution**: Average runtime per audit is 2–6 seconds (well under the 5-minute limit).
- **Fault-Tolerant / Resilient**: Every sub-skill catches its own network/parsing errors; the orchestrator encapsulates sub-skill execution so one failing domain or blocked check never halts the audit.
- **agentskills.io Standard**: Every skill folder contains a valid `SKILL.md` with YAML frontmatter (name, description, license: Apache-2.0) and markdown sections (`When to use`, `Inputs`, `Procedure`, `Output`).

---

## 8. Empirical Benchmark — 512 Real Domains

The `benchmarks/benchmark_results.json` and interactive `benchmarks/benchmark_executive_report.html`
contain audited results from a live multi-threaded batch run across **512 real websites** in **8 industry sectors**
evaluated with the weighted pillar model (Crawl 40%, Structured Data 30%, Freshness 15%, Engagement 15%).

| Metric | Value |
|---|---|
| Domains audited | 512 |
| Sectors covered | E-Commerce, B2B SaaS, Media, Developer Tools, Financial Services, Healthcare, Travel, Government/Education |
| Execution time | 526 seconds (~8.8 min total, ~1s per domain via concurrency) |
| Global average GEO score | **86.4 / 100** |
| Score range | 62 – 98 |
| Fault containment | 100% (0 unhandled crashes across all 512 domains) |

**Top 5 failure modes across all 512 domains:**

| Rank | Finding | Domains Affected |
|---|---|---|
| 1 | Low Text-to-HTML Ratio (DOM Bloat) | 315 (61.5%) |
| 2 | Missing Deep-Link Target Anchors for AI Citations | 284 (55.5%) |
| 3 | Sitemap Missing or Invalid | 260 (50.8%) |
| 4 | Intrusive Modal Overlay on Initial View | 203 (39.6%) |
| 5 | Missing Temporal & Freshness Metadata | 196 (38.3%) |

The benchmark data validates that the audit heuristics are detecting real, widespread issues
across production websites — not just catching trivial edge cases. Evaluators can inspect the interactive report
at `benchmarks/benchmark_executive_report.html` or run live subsets via `python benchmarks/run_live_benchmark_500.py --limit 10`.
