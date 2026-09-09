# PROJECT.md — Architecture & Engineering Specification

## 1. Project Identity

- **Name**: `brand-ai-readiness-audit`
- **Standard**: [agentskills.io](https://agentskills.io) Agent Skill Marketplace Specification
- **License**: Apache-2.0
- **Primary Runtime**: Python 3.8+
- **Purpose**: Autonomous audit of target websites for AI Discoverability (Generative Engine Optimization - GEO) and On-Site Engagement readiness.

---

## 2. Architecture & Code Layout

The project follows the standard agentskills.io layout:

```
brand-ai-readiness-audit/
├── marketplace.json                      # agentskills.io Marketplace Manifest
├── README.md                             # Comprehensive package documentation
├── PROJECT.md                            # System architecture & layout spec
├── TEST_INFRA.md                         # Test infrastructure documentation
├── requirements.txt                      # Runtime dependencies (requests, beautifulsoup4)
├── skills/
│   ├── audit-orchestrator/               # Entrypoint orchestrator skill
│   │   ├── SKILL.md                      # agentskills.io skill definition
│   │   └── scripts/
│   │       └── run_audit.py              # Master orchestrator implementation
│   ├── crawl-render-audit/               # Sub-skill: Crawlability & CSR checks
│   │   ├── SKILL.md                      # agentskills.io skill definition
│   │   └── scripts/
│   │       └── check_crawler_render.py   # Crawler & rendering audit implementation
│   ├── structured-data-audit/            # Sub-skill: Schema.org & JSON-LD checks
│   │   ├── SKILL.md                      # agentskills.io skill definition
│   │   └── scripts/
│   │       └── check_structured_data.py  # Structured data audit implementation
│   ├── freshness-corroboration/          # Sub-skill: Temporal & sitemap checks
│   │   ├── SKILL.md                      # agentskills.io skill definition
│   │   └── scripts/
│   │       └── check_freshness.py        # Content freshness audit implementation
│   └── engagement-bounce-audit/          # Sub-skill: UX & citation anchor checks
│       ├── SKILL.md                      # agentskills.io skill definition
│       └── scripts/
│           └── check_engagement.py       # Engagement & friction audit implementation
└── .agents/                              # Agent coordination metadata (briefings, plans)
```

---

## 3. Interface Contracts

### 3.1 Marketplace Manifest (`marketplace.json`)
- Exactly 5 skills declared in `skills` array.
- Exactly 1 skill with `entrypoint: true` (`audit-orchestrator`).
- All other 4 skills have `entrypoint: false`.

### 3.2 Skill Definitions (`SKILL.md`)
Each skill must provide:
- Valid YAML frontmatter: `name`, `description`, `license: Apache-2.0`, `metadata` (version, author, category, tags).
- Required Markdown sections:
  1. `# <Skill Title>`
  2. `## When to use`
  3. `## Inputs`
  4. `## Procedure`
  5. `## Output`

### 3.3 CLI Invocation Contract
Every script supports:
- `--url <URL>`
- Positional argument `<URL>`
- Exit code 0 on successful audit execution.
- Valid JSON to `stdout`.

### 3.4 Orchestrator JSON Report Contract
```json
{
  "site": "<url>",
  "audited_at": "<ISO-8601 timestamp>",
  "summary": {
    "total_findings": <int>,
    "critical": <int>,
    "high": <int>,
    "medium": <int>
  },
  "findings": [
    {
      "id": "F-001",
      "title": "<String>",
      "severity": "critical|high|medium",
      "evidence": "<String>",
      "suggested_action": {
        "summary": "<String>",
        "priority": "high|medium|low"
      }
    }
  ]
}
```

---

## 4. Engineering Standards & Integrity Guarantees

1. **Zero External Paid APIs**: Only standard Python libraries + `requests` and `beautifulsoup4`.
2. **Network Resiliency**: Bounded 10s timeouts, safe exception handling, zero unhandled crash policy.
3. **No Fabrication / Hardcoding**: All parsers perform genuine DOM, header, and robots.txt analysis.
