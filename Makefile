SHELL := /bin/bash
.DEFAULT_GOAL := help
.PHONY: help install format format-check lint typecheck test test-python test-web build api worker web keys data-synthea up up-full up-ocr-cpu up-ocr-gpu showcase-up showcase-check showcase-reset showcase-scale ocr-smoke ocr-smoke-gpu security-smoke full-profile-smoke recovery-smoke mutation container-scan ocr-container-scan down logs seed reset-demo screenshots backup restore clean-preview clean-confirm openapi case-study docs lock-check security-audit ci-static ci-test ci-integration ci verify-all benchmark-100m

COMPOSE := docker compose -f infra/compose/compose.yaml
IMAGE_PREFIX := $(or $(COMPOSE_PROJECT_NAME),ehrfs)
SHOWCASE_EVENTS ?= 1000000
SHOWCASE_PARTITION_ROWS ?= 50000

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*## "; printf "EHRFS local commands\n\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install locked Python and frontend dependencies
	uv sync --frozen
	pnpm install --frozen-lockfile

format: ## Format Python and frontend sources
	uv run ruff format src apps/api/src tests scripts migrations airflow services/ocr/app.py
	uv run ruff check --fix src apps/api/src tests scripts migrations airflow services/ocr/app.py
	pnpm --dir apps/web format
	pnpm --dir apps/web exec prettier --write ../../docs/case-study/case-study.fr.html ../../docs/case-study/case-study.css

format-check: ## Verify formatting without writing
	uv run ruff format --check src apps/api/src tests scripts migrations airflow services/ocr/app.py
	pnpm --dir apps/web exec prettier --check . ../../docs/case-study/case-study.fr.html ../../docs/case-study/case-study.css

lint: ## Run static linters
	uv run ruff check src apps/api/src tests scripts migrations airflow services/ocr/app.py
	pnpm lint

typecheck: ## Run strict Python and TypeScript checks
	uv run mypy src apps/api/src tests airflow
	pnpm typecheck

test-python: ## Run Python unit/property/security tests
	uv run pytest --cov=ehrfs --cov=ehrfs_api --cov-branch --cov-report=term-missing --cov-report=json:coverage.json --cov-fail-under=95 -q
	uv run python scripts/check_critical_coverage.py coverage.json

test-web: ## Run frontend unit and component tests
	pnpm test

test: test-python test-web ## Run all non-container tests

build: ## Build the production web application and Python package
	pnpm build
	uv build
	uv run python scripts/validate_wheel.py

api: ## Run the API locally
	uv run uvicorn ehrfs_api.app:app --reload --host 127.0.0.1 --port 8000

worker: ## Run the durable worker locally
	uv run python -m ehrfs.orchestration.worker

web: ## Run the Vite development server
	pnpm dev

keys: ## Generate a local Ed25519 signing keypair
	@if [[ ! -f .local/keys/ehrfs_signing_key || ! -f .local/keys/ehrfs_signing_key.pub ]]; then \
		uv run ehrfs keys generate; \
	fi
	@chmod 0750 .local/keys
	@chmod 0640 .local/keys/ehrfs_signing_key
	@chmod 0644 .local/keys/ehrfs_signing_key.pub

data-synthea: ## Generate the ignored 500-patient Synthea FHIR R4 profile
	scripts/generate_synthea.sh 500 20260828 20260828

up: keys ## Start the core profile
	$(COMPOSE) up --build -d

up-full: keys ## Start core plus Airflow and observability
	EHRFS_OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317 $(COMPOSE) --profile full up --build -d

up-ocr-cpu: keys ## Start core plus isolated local PaddleOCR CPU inference
	$(COMPOSE) --profile ocr-cpu up --build -d

up-ocr-gpu: keys ## Start core plus isolated local PaddleOCR GPU inference
	$(COMPOSE) --profile ocr-gpu up --build -d

showcase-up: keys ## Start, reset, and verify the complete CPU showcase
	@test -f .env || (echo 'Missing .env: run cp .env.example .env' && exit 2)
	EHRFS_OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317 $(COMPOSE) --profile full --profile ocr-cpu up --build -d --wait --wait-timeout 600
	$(COMPOSE) exec -T api ehrfs demo reset
	uv run python scripts/showcase_check.py --wait-seconds 120

showcase-check: ## Check every browser-facing showcase service
	uv run python scripts/showcase_check.py

showcase-reset: ## Restore only the deterministic synthetic opening scenario
	$(COMPOSE) exec -T api ehrfs demo reset

showcase-scale: ## Run a bounded scale validation; set SHOWCASE_EVENTS=100000000 for the full proof
	uv run --group benchmark python scripts/benchmark_100m.py --events $(SHOWCASE_EVENTS) --partition-rows $(SHOWCASE_PARTITION_ROWS) --output artifacts/benchmarks/answer-events-showcase.json

ocr-smoke: ## Run and measure live local OCR against the synthetic French fixture
	$(COMPOSE) --profile ocr-cpu up --build -d --wait --wait-timeout 600 ocr-cpu
	uv run python scripts/ocr_smoke.py

ocr-smoke-gpu: ## Run and measure GPU OCR against the same synthetic fixture
	$(COMPOSE) --profile ocr-gpu up --build -d --wait --wait-timeout 600 ocr-gpu
	uv run python scripts/ocr_smoke.py --endpoint http://127.0.0.1:8082 --output artifacts/benchmarks/ocr-gpu.json

security-smoke: ## Verify live ClamAV clean and EICAR test-payload decisions
	$(COMPOSE) --profile security up -d --wait --wait-timeout 240 --force-recreate clamav
	uv run python scripts/clamav_smoke.py

full-profile-smoke: ## Verify Airflow and the complete observability profile
	$(MAKE) up-full
	curl --fail --silent --show-error --retry 60 --retry-delay 1 --retry-max-time 120 --retry-all-errors http://127.0.0.1:9090/-/ready >/dev/null
	curl --fail --silent --show-error --retry 60 --retry-delay 1 --retry-max-time 120 --retry-all-errors http://127.0.0.1:13133/ >/dev/null
	curl --fail --silent --show-error --retry 60 --retry-delay 1 --retry-max-time 120 --retry-all-errors http://127.0.0.1:3001/api/health >/dev/null
	curl --fail --silent --show-error --retry 60 --retry-delay 1 --retry-max-time 120 --retry-all-errors http://127.0.0.1:8088/api/v2/monitor/health >/dev/null

recovery-smoke: ## Create, checksum, restore, and compare an isolated recovery copy
	scripts/recovery_smoke.sh

mutation: ## Enforce the critical-semantic mutation score and zero-survivor gate
	uv run --group mutation mutmut run
	uv run --group mutation mutmut export-cicd-stats
	uv run python scripts/check_mutation_score.py mutants/mutmut-cicd-stats.json

down: ## Stop services without deleting data
	$(COMPOSE) down

logs: ## Follow core service logs
	$(COMPOSE) logs --tail=200 -f api worker web

seed: ## Idempotently seed the deterministic demonstration
	$(COMPOSE) exec -T api ehrfs demo run

reset-demo: ## Reset only synthetic demo rows
	$(COMPOSE) exec -T api ehrfs demo reset

screenshots: ## Capture all workspaces at desktop and mobile acceptance sizes
	$(COMPOSE) up --build -d --wait --wait-timeout 240
	$(COMPOSE) exec -T api ehrfs demo reset
	EHRFS_SCREENSHOT_OUTPUT_DIR=../../docs/assets/generated pnpm --dir apps/web screenshots

backup: ## Create a checksummed backup at BACKUP_DIR (must not exist)
	@test -n "$(BACKUP_DIR)" || (echo 'BACKUP_DIR is required' && exit 2)
	scripts/backup.sh "$(BACKUP_DIR)"

restore: ## Restore BACKUP_DIR into a new RECOVERY_DB
	@test -n "$(BACKUP_DIR)" || (echo 'BACKUP_DIR is required' && exit 2)
	scripts/restore.sh "$(BACKUP_DIR)" "$(or $(RECOVERY_DB),ehrfs_restore)"

clean-preview: ## Show exactly which local generated artifacts a clean would remove
	@printf '%s\n' '.coverage' 'coverage/' 'apps/web/coverage/' 'apps/web/dist/' 'artifacts/' 'data/generated/* (except .gitkeep)'

clean-confirm: ## Remove previewed generated artifacts; requires CONFIRM=clean-generated
	@test "$(CONFIRM)" = "clean-generated" || (echo 'Refusing: run make clean-preview, then CONFIRM=clean-generated make clean-confirm' && exit 2)
	rm -rf -- .coverage coverage apps/web/coverage apps/web/dist artifacts
	find data/generated -mindepth 1 ! -name .gitkeep -delete

openapi: ## Regenerate OpenAPI and TypeScript API contract
	uv run python scripts/export_openapi.py
	pnpm --dir apps/web exec openapi-typescript ../../docs/api/openapi.json -o src/api/openapi-schema.ts
	pnpm --dir apps/web exec prettier --write src/api/openapi-schema.ts

case-study: ## Render diagrams and the exact eight-page French PDF
	pnpm --dir apps/web exec node scripts/render-case-study-diagrams.mjs
	pnpm --dir apps/web exec node scripts/build-case-study.mjs
	uv run python scripts/validate_case_study.py

docs: openapi case-study ## Regenerate and validate public documentation

lock-check: ## Verify dependency lockfiles without changing them
	uv lock --check
	uv lock --check --directory services/ocr
	uv lock --check --directory services/ocr-gpu
	pnpm install --frozen-lockfile --lockfile-only

security-audit: ## Audit dependencies and scan committed files for secrets
	uv run pip-audit
	pnpm audit --audit-level high
	uvx --from semgrep==1.166.0 semgrep scan --config .semgrep.yml --error --metrics=off
	uv run pre-commit run gitleaks --all-files

container-scan: ## Fail on fixable high/critical findings in locally built runtime images
	mkdir -p artifacts/security
	docker run --rm --volume /var/run/docker.sock:/var/run/docker.sock --volume ehrfs-trivy-cache:/root/.cache --volume "$(CURDIR)/artifacts/security:/reports" --entrypoint /bin/sh aquasec/trivy:0.74.0@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969 -ceu 'for target in $(IMAGE_PREFIX)-api:latest $(IMAGE_PREFIX)-worker:latest $(IMAGE_PREFIX)-web:latest; do safe=$$(printf "%s" "$$target" | tr ":/" "--"); trivy image --exit-code 1 --ignore-unfixed --severity CRITICAL,HIGH --scanners vuln --format json --output "/reports/trivy-$$safe.json" "$$target"; echo "Trivy scan passed: $$target"; done'

ocr-container-scan: ## Scan the isolated live-OCR runtime after its profile build
	mkdir -p artifacts/security
	docker run --rm --volume /var/run/docker.sock:/var/run/docker.sock --volume ehrfs-trivy-cache:/root/.cache --volume "$(CURDIR)/artifacts/security:/reports" --entrypoint /usr/local/bin/trivy aquasec/trivy:0.74.0@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969 image --exit-code 1 --ignore-unfixed --severity CRITICAL,HIGH --scanners vuln --format json --output /reports/trivy-$(IMAGE_PREFIX)-ocr-cpu-latest.json $(IMAGE_PREFIX)-ocr-cpu:latest
	@echo 'Trivy scan passed: $(IMAGE_PREFIX)-ocr-cpu:latest'

ci-static: lock-check format-check lint typecheck docs security-audit ## Run static, documentation, and supply-chain checks
	uv run python scripts/export_openapi.py --check
	uv run python scripts/validate_repository.py

ci-test: test build ## Run unit, property, contract, security, and build checks

ci-integration: keys ## Run container-backed and browser acceptance checks
	$(COMPOSE) up --build -d
	$(MAKE) container-scan
	uv run pytest -m integration -q
	EHRFS_E2E_EXTERNAL=1 pnpm test:e2e
	uv run python scripts/determinism_check.py
	$(COMPOSE) config --quiet
	curl --fail --silent http://127.0.0.1:8000/api/v1/health/ready >/dev/null
	curl --fail --silent http://127.0.0.1:3000/ >/dev/null

ci: ci-static ci-test ci-integration ## Run the local pull-request quality pipeline

benchmark-100m: ## Measure 100 million bounded answer events
	uv run --group benchmark python scripts/benchmark_100m.py

verify-all: ci ## Run every extended verification gate; GPU is intentionally fail-closed
	$(MAKE) mutation
	$(MAKE) full-profile-smoke
	$(MAKE) security-smoke
	$(MAKE) recovery-smoke
	$(MAKE) ocr-smoke
	$(MAKE) ocr-container-scan
	$(MAKE) screenshots
	$(MAKE) case-study
	$(MAKE) benchmark-100m
	$(MAKE) ocr-smoke-gpu
