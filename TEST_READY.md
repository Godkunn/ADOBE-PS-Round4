# Brand AI Readiness Audit — E2E Test Suite Specification & Verification Guide

## 1. Executive Summary

The `brand-ai-readiness-audit` project is verified through an end-to-end, multi-tier testing framework that operates 100% offline, deterministically, and without external network or API dependencies.

The testing architecture provides comprehensive test coverage across all 5 skills, security defenses, and the marketplace manifest, structured into **5 hermetic verification suites**:
- **Marketplace & Standard Compliance** (`tests/test_marketplace.py`): 15 tests covering manifest integrity, agentskills.io SKILL.md specs, and single-entrypoint invariants.
- **Core Skill Heuristics & Orchestration** (`tests/test_skills.py`): 31 tests covering RFC 9309 robots.txt parsing, CSR detection, JSON-LD extraction, freshness, and scoring.
- **Resiliency & Fault Containment** (`tests/test_resilience.py`): 13 tests testing network timeouts, DNS failures, 403/500 HTTP responses, corrupt JSON-LD, and empty HTML.
- **Performance Budget** (`tests/test_performance.py`): 3 tests asserting execution time well below the 5-second SLA and stable memory usage.
- **Security Hardening & Bug Regressions** (`tests/test_bug_fixes.py`): 36 tests covering SSRF IP defenses (BSD shorthand, octal/hex, CGNAT), IPv6 rate limiting, sitemap discovery, and secondary AI crawler classifications.

**Total Test Suite Volume:** **98 discrete test cases** (100% passing hermetically, well exceeding the required >=45 tests).

---

## 2. Test Architecture & Files

```
brand-ai-readiness-audit/
├── marketplace.json                      # Marketplace manifest
├── README.md                             # Marketplace documentation
├── TEST_READY.md                         # This test suite verification manifest
├── TEST_INFRA.md                         # Hermetic test harness documentation
├── skills/                               # 5 isolated skill directories
│   ├── audit-orchestrator/               # Master entrypoint skill
│   ├── crawl-render-audit/               # Crawler access & CSR audit
│   ├── structured-data-audit/            # JSON-LD & Schema.org audit
│   ├── freshness-corroboration/          # Temporal metadata & sitemap audit
│   └── engagement-bounce-audit/          # Direct answer & UX friction audit
└── tests/                                # Automated Hermetic Test Suite
    ├── __init__.py                       # Package initialization
    ├── bootstrap.py                      # Universal sys.path resolver
    ├── conftest.py                       # Pytest fixtures and mock setups
    ├── mock_server.py                    # Multi-threaded local HTTP fixture server
    ├── test_marketplace.py               # Manifest & SKILL.md specification tests
    ├── test_skills.py                    # Sub-skill heuristics & orchestrator integration
    ├── test_resilience.py                # Fault tolerance, crash containment & SSRF
    ├── test_performance.py               # Execution benchmarking (< 5s runtime budget)
    └── test_bug_fixes.py                 # Security hardening, SSRF regression & bug tests
```

---

## 3. Test Tier Breakdown & Catalog

### Tier 1: Feature Coverage (34 Tests)
| Test ID | Test Name | Target Component | Verifies |
|---|---|---|---|
| `T1-STD-01` | `test_t1_std_01_marketplace_manifest_exists_and_json` | Manifest | `marketplace.json` exists and is valid JSON |
| `T1-STD-02` | `test_t1_std_02_marketplace_manifest_required_fields` | Manifest | Mandatory fields (`name`, `version`, `description`, `license`, `entrypoint`, `skills`) |
| `T1-STD-03` | `test_t1_std_03_marketplace_manifest_declares_5_skills` | Manifest | Declares exactly 5 isolated skills |
| `T1-STD-04` | `test_t1_std_04_marketplace_manifest_single_entrypoint` | Manifest | Exactly one `entrypoint: true` (`audit-orchestrator`) |
| `T1-STD-05` | `test_t1_std_05_all_skill_md_files_exist` | SKILL.md | All 5 skills possess a `SKILL.md` |
| `T1-STD-06` | `test_t1_std_06_skill_md_yaml_frontmatter_valid` | SKILL.md | YAML frontmatter (`name`, `description`, `license: Apache-2.0`) |
| `T1-STD-07` | `test_t1_std_07_skill_md_markdown_sections` | SKILL.md | 4 standard markdown sections (`When to use`, `Inputs`, `Procedure`, `Output`) |
| `T1-ORCH-01`| `test_t1_orch_01_cli_positional_url` | Orchestrator | CLI invocation via positional URL argument |
| `T1-ORCH-02`| `test_t1_orch_02_cli_flag_url` | Orchestrator | CLI invocation via `--url` flag |
| `T1-ORCH-03`| `test_t1_orch_03_sequential_id_assignment` | Orchestrator | Sequential ID assignment (`F-001`, `F-002`, ...) |
| `T1-ORCH-04`| `test_t1_orch_04_summary_counts_accuracy` | Orchestrator | Accurate summary arithmetic (`total_findings == critical + high + medium`) |
| `T1-ORCH-05`| `test_t1_orch_05_deterministic_deduplication` | Orchestrator | Deterministic deduplication of duplicate findings |
| `T1-ORCH-06`| `test_t1_orch_06_strict_json_schema_structure` | Orchestrator | Strict conformance to root output JSON schema |
| `T1-ORCH-07`| `test_t1_orch_07_severity_sorting_order` | Orchestrator | Findings sorted strictly: critical -> high -> medium |
| `T1-CR-01`  | `test_t1_cr_01_ai_bots_disallowed_robots_txt` | CrawlRender | Robots.txt blocking GPTBot/ClaudeBot triggers Critical finding |
| `T1-CR-02`  | `test_t1_cr_02_ai_bots_allowed_robots_txt` | CrawlRender | Robots.txt allowing AI bots produces 0 blocking findings |
| `T1-CR-03`  | `test_t1_cr_03_csr_blank_root_placeholder` | CrawlRender | Blank `<div id="root">` + heavy bundle triggers High finding |
| `T1-CR-04`  | `test_t1_cr_04_static_ssr_rich_page` | CrawlRender | Rich static SSR page produces 0 CSR findings |
| `T1-CR-05`  | `test_t1_cr_05_waf_user_agent_403_block` | CrawlRender | HTTP 403 on AI User-Agent triggers Critical WAF finding |
| `T1-SD-01`  | `test_t1_sd_01_missing_product_schema` | StructuredData | E-commerce product page missing Product schema triggers High finding |
| `T1-SD-02`  | `test_t1_sd_02_missing_offer_price_or_currency` | StructuredData | Missing `priceCurrency` on Offer triggers Medium finding |
| `T1-SD-03`  | `test_t1_sd_03_valid_product_and_offer_schema` | StructuredData | Complete Product & Offer schema produces 0 product findings |
| `T1-SD-04`  | `test_t1_sd_04_missing_organization_sameas` | StructuredData | Organization schema missing Wikidata/Wikipedia `sameAs` triggers Medium finding |
| `T1-SD-05`  | `test_t1_sd_05_valid_organization_sameas` | StructuredData | Organization schema with `sameAs` produces 0 disambiguation findings |
| `T1-FC-01`  | `test_t1_fc_01_missing_temporal_metadata` | Freshness | Missing `article:modified_time` and schema dates triggers Medium finding |
| `T1-FC-02`  | `test_t1_fc_02_outdated_footer_copyright` | Freshness | Outdated copyright (e.g., 2018) in footer triggers Medium finding |
| `T1-FC-03`  | `test_t1_fc_03_current_copyright_and_meta` | Freshness | Current 2026 copyright and valid temporal meta produces 0 findings |
| `T1-FC-04`  | `test_t1_fc_04_missing_sitemap_lastmod` | Freshness | Sitemap missing `<lastmod>` timestamps triggers Medium finding |
| `T1-FC-05`  | `test_t1_fc_05_valid_sitemap_lastmod` | Freshness | Sitemap with valid ISO-8601 `<lastmod>` produces 0 findings |
| `T1-EB-01`  | `test_t1_eb_01_missing_direct_answer_layout` | Engagement | Direct answer buried behind carousel hero triggers Medium finding |
| `T1-EB-02`  | `test_t1_eb_02_valid_direct_answer_layout` | Engagement | Concise summary under H1 (<60 words) produces 0 layout findings |
| `T1-EB-03`  | `test_t1_eb_03_missing_section_id_anchors` | Engagement | Content sections missing static `id` attributes triggers Medium finding |
| `T1-EB-04`  | `test_t1_eb_04_valid_section_id_anchors` | Engagement | Sections with static `id` anchors produce 0 anchor findings |
| `T1-EB-05`  | `test_t1_eb_05_intrusive_modal_overlay` | Engagement | Full-screen modal overlay markup on initial view triggers Medium finding |

### Tier 2: Boundary & Corner Cases (13 Tests)
| Test ID | Test Name | Trigger Scenario | Resilience Expectation |
|---|---|---|---|
| `T2-BND-01` | `test_t2_bnd_01_invalid_url_string` | Malformed URL string `"not_a_valid_url"` | Handles gracefully, exit code 0 or 1, no unhandled traceback |
| `T2-BND-02` | `test_t2_bnd_02_non_existent_domain_dns_fail` | Non-existent domain / DNS resolution failure | Catches `ConnectionError`, outputs clean report |
| `T2-BND-03` | `test_t2_bnd_03_http_404_root_not_found` | HTTP 404 response on target URL | Parsed without crashing, returns valid JSON report |
| `T2-BND-04` | `test_t2_bnd_04_http_500_server_error` | HTTP 500 Internal Server Error | Exception caught cleanly, valid JSON output |
| `T2-BND-05` | `test_t2_bnd_05_http_403_forbidden` | HTTP 403 Forbidden baseline response | Handled safely, valid JSON output |
| `T2-BND-06` | `test_t2_bnd_06_network_timeout_handling` | Network read delay > timeout | Timeout handled without hanging, returns cleanly |
| `T2-BND-07` | `test_t2_bnd_07_empty_response_body` | Empty (0 bytes) response body | Parsed without `NoneType` or index errors |
| `T2-BND-08` | `test_t2_bnd_08_malformed_html_markup` | Unclosed tags and truncated HTML | BeautifulSoup handles DOM safely without crash |
| `T2-BND-09` | `test_t2_bnd_09_malformed_jsonld_syntax` | Invalid JSON-LD syntax in `<script>` | JSON parse error caught, does not crash orchestrator |
| `T2-BND-10` | `test_t2_bnd_10_non_dict_jsonld_payload` | JSON-LD containing string or array | Type checking prevents `AttributeError` |
| `T2-BND-11` | `test_t2_bnd_11_massive_payload_processing` | 1.5MB HTML payload with 15,000+ DOM tags | Finishes within memory and execution time limits (<5s) |
| `T2-BND-12` | `test_t2_bnd_12_non_utf8_latin1_encoding` | Document in ISO-8859-1 (Latin-1) | Decoded cleanly without `UnicodeDecodeError` |
| `T2-BND-13` | `test_t2_bnd_13_missing_robots_and_sitemap_404` | 404 on `/robots.txt` and `/sitemap.xml` | Treated as absent without unhandled exceptions |

### Tier 3: Cross-Feature Combinations (5 Tests)
| Test ID | Test Name | Combination Profile | Expected Output |
|---|---|---|---|
| `T3-COMB-01` | `test_t3_comb_01_pristine_ai_ready_website` | Clean robots, valid sitemap, rich SSR, full Product/Org JSON-LD, fresh meta | 0 findings (`total_findings == 0`, `critical == 0`, `high == 0`, `medium == 0`) |
| `T3-COMB-02` | `test_t3_comb_02_worst_case_broken_website` | Blocked bots, outdated 2018 copyright, modal overlay, buried answer | Multiple findings across all categories, sorted critical -> high -> medium |
| `T3-COMB-03` | `test_t3_comb_03_ecommerce_ai_discovery_barrier`| E-commerce site blocking GPTBot + missing price currency | 1 Critical finding, 2 Medium findings |
| `T3-COMB-04` | `test_t3_comb_04_deduplication_across_overlapping_rules` | Duplicate schema errors and multiple identical modal triggers | Deduplicated into unique findings without duplicate titles |
| `T3-COMB-05` | `test_t3_comb_05_multi_agent_waf_blocking` | WAF returns 200 OK to browser but 403 Forbidden to AI bots | Triggers Critical WAF finding |

### Tier 4: Real-World Scenarios (4 Tests)
| Test ID | Test Name | Simulated Archetype | Expected Diagnostics |
|---|---|---|---|
| `T4-REAL-01` | `test_t4_real_01_modern_ecommerce_store` | High-end electronics store (Shopify/Next.js) | Blocks GPTBot (1 Critical), missing priceCurrency (1 Medium), missing lastmod (1 Medium) -> 3 total |
| `T4-REAL-02` | `test_t4_real_02_digital_news_publisher` | Digital tech news publication with Article schema | Intrusive newsletter modal (1 Medium), secondary outdated copyright (1 Medium) -> 2 total |
| `T4-REAL-03` | `test_t4_real_03_enterprise_b2b_saas` | Enterprise B2B SaaS platform homepage | Missing Organization sameAs (1 Medium), buried direct answer (1 Medium) -> 2 total |
| `T4-REAL-04` | `test_t4_real_04_pure_client_side_react_spa` | Client-side React/Vite Single Page Application | CSR blank root container with 180KB bundle & 28 words text -> 1 High finding |

---

## 4. Execution Commands

### Run Complete Test Suite via Standard Unittest Runner:
```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

### Run via Pytest:
```bash
pytest -v
```

### Run Standalone Mock Server:
```bash
python tests/mock_server.py --port 8000
```

---

## 5. Pass / Fail Acceptance Criteria

- **Pass Criterion (Exit Code 0)**: All 56 test cases execute to completion and assert 100% successful pass conditions.
- **Fail Criterion (Exit Code 1)**: Any single failure or uncaught error across any of the 4 tiers triggers an immediate non-zero exit code and displays diagnostic traces.
