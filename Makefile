.PHONY: help install test audit lint docker-build docker-run clean pack

PYTHON ?= python
URL ?= https://example.com

help:
	@echo "Brand AI Readiness Audit — Developer Commands:"
	@echo "  make install     - Install required dependencies"
	@echo "  make test        - Run comprehensive test suite"
	@echo "  make audit       - Execute audit on URL (e.g. make audit URL=https://example.com)"
	@echo "  make docker-build- Build Docker container"
	@echo "  make docker-run  - Run audit in Docker container"
	@echo "  make pack        - Rebuild submission ZIP package"

install:
	$(PYTHON) -m pip install -r requirements.txt

test:
	$(PYTHON) -m unittest discover -s tests

audit:
	$(PYTHON) skills/audit-orchestrator/scripts/run_audit.py $(URL)

docker-build:
	docker build -t brand-ai-readiness-audit:latest .

docker-run:
	docker run --rm brand-ai-readiness-audit:latest $(URL)

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

pack:
	$(PYTHON) package_verify.py
