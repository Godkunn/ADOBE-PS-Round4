# Operational Runbook & Production Deployment

## 1. Overview
This runbook provides enterprise operational procedures for building, testing, containerizing, and integrating the **Brand AI-Readiness Audit Marketplace** into autonomous agent pipelines, CI/CD workflows, and production monitoring stacks.

---

## 2. Local Development & Testing

### 2.1. Prerequisites
- Python 3.8+ (Supports Python 3.8, 3.9, 3.10, 3.11, 3.12, 3.13)
- Standard packages: `requests>=2.28.0`, `beautifulsoup4>=4.11.0`

### 2.2. Installation
```bash
# Standard dependency installation
pip install -r requirements.txt

# Or editable package installation via PEP 517/621
pip install -e .
```

### 2.3. Automated Test Execution
```bash
# Run full automated test harness (Unit, Resilience, Manifest)
python -m unittest discover -s tests

# Using Makefile
make test
```

---

## 3. Production Execution & CLI Reference

### 3.1. Standard Orchestrator Invocation
```bash
# Basic stdout execution (machine-readable strict JSON)
python skills/audit-orchestrator/scripts/run_audit.py https://example.com

# Save to persistent report file
python skills/audit-orchestrator/scripts/run_audit.py https://example.com --output /path/to/report.json

# Custom network timeout configuration
python skills/audit-orchestrator/scripts/run_audit.py --url https://example.com --timeout 15
```

### 3.2. Individual Sub-Skill Execution
Each sub-skill operates as an independent micro-auditor:
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

---

## 4. Containerized Deployment (Docker & Kubernetes)

### 4.1. Docker Container Build
```bash
# Build multi-stage minimal alpine container
docker build -t brand-ai-readiness-audit:latest .

# Run audit inside isolated container
docker run --rm brand-ai-readiness-audit:latest https://example.com
```

### 4.2. Docker Compose
```bash
# Run with mounted output directory
docker-compose run --rm audit-agent https://example.com
```

---

## 5. Reliability, SRE & Fault-Tolerant Design
- **Non-Destructive Guarantee:** 100% read-only GET requests with safe HTTP timeouts.
- **Fail-Safe Sandboxing:** Sub-skill failures are caught and converted into structured notices rather than unhandled tracebacks.
- **Performance:** Under 5 seconds execution budget for complete 4-skill orchestration.
