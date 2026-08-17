UV ?= uv
UV_CACHE_DIR ?= $(CURDIR)/.uv-cache
# The shared packages are path-based, not installed, so tooling needs them on the path.
PYTHONPATH_PARTS = packages/contracts/python:packages/docpipe/python
UV_RUN = UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) run
BENCH_RUN = PYTHONPATH=$(PYTHONPATH_PARTS) $(UV_RUN)
# `app.*` lives under services/api and is not an installed package.
API_RUN = PYTHONPATH=services/api:$(PYTHONPATH_PARTS) $(UV_RUN)
BENCH_OUTPUT ?= artifacts/parser-bench/local
BENCH_PARSERS ?= pymupdf
NPM ?= npm
COMPOSE_FILE ?= infra/compose/docker-compose.yml

.PHONY: setup backend-format-check backend-lint backend-typecheck backend-test \
	frontend-format-check frontend-lint frontend-typecheck frontend-test frontend-build \
	compose-config docs-check repository-hygiene secret-scan check dev \
	parser-contract-tests parser-benchmark-smoke parser-bench parser-fixtures \
	ingestion-integration admin-parser-golden-tests db-migration-test worker serve-api \
	web-component-tests web-e2e-smoke feedback-tests

setup:
	UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) sync --locked
	$(NPM) ci --prefix apps/web

backend-format-check:
	$(UV_RUN) ruff format --check services/api services/ai-worker packages tools tests benchmarks

backend-lint:
	$(UV_RUN) ruff check services/api services/ai-worker packages tools tests benchmarks

backend-typecheck:
	$(UV_RUN) mypy

backend-test:
	$(UV_RUN) pytest -q

frontend-format-check:
	$(NPM) run format:check --prefix apps/web

frontend-lint:
	$(NPM) run lint --prefix apps/web

frontend-typecheck:
	$(NPM) run typecheck --prefix apps/web

frontend-test:
	$(NPM) run test:run --prefix apps/web

frontend-build:
	$(NPM) run build --prefix apps/web

# Phase 1 document-pipeline gates.
parser-contract-tests:
	$(UV_RUN) pytest tests/unit tests/contract -q

parser-benchmark-smoke:
	$(UV_RUN) pytest tests/benchmark -q
	$(BENCH_RUN) python -m tools.parser_bench validate --manifest benchmarks/parser/manifest.jsonl

# Full benchmark run. Heavy parsers are only included when installed locally; see
# benchmarks/parser/README.md.
parser-bench:
	$(BENCH_RUN) python -m tools.parser_bench run \
		--manifest benchmarks/parser/manifest.jsonl \
		--parsers $(BENCH_PARSERS) \
		--output $(BENCH_OUTPUT)

parser-fixtures:
	$(UV_RUN) python benchmarks/parser/generate_fixtures.py
	$(UV_RUN) python tests/fixtures/generate_recordings.py

# Phase 2 ingestion gates.
ingestion-integration:
	$(UV_RUN) pytest services/api/tests/test_upload_api.py services/api/tests/test_jobs.py \
		services/api/tests/test_storage.py services/api/tests/test_state_machine.py \
		services/api/tests/test_ingestion_integration.py tests/unit/test_ingestion_pipeline.py \
		tests/unit/test_parser_strategy.py -q

admin-parser-golden-tests:
	$(UV_RUN) pytest tests/golden -q

db-migration-test:
	$(UV_RUN) pytest services/api/tests/test_migrations.py -q

# Phase 3 correction feedback gate.
feedback-tests:
	$(UV_RUN) pytest services/api/tests/test_feedback_api.py -q

# Drain the parse queue once against the configured database and storage.
worker:
	$(API_RUN) python -m app.worker --once

# Serve the API for local/E2E use.
serve-api:
	$(API_RUN) uvicorn app.main:app --host $${API_HOST:-127.0.0.1} --port $${API_PORT:-8000}

web-component-tests:
	$(NPM) run test:run --prefix apps/web

web-e2e-smoke:
	$(NPM) run test:e2e --prefix apps/web

compose-config:
	docker compose -f $(COMPOSE_FILE) config --quiet

docs-check:
	$(UV_RUN) python tools/ci/check_docs.py

repository-hygiene:
	$(UV_RUN) python tools/ci/check_repo_hygiene.py

secret-scan:
	$(UV_RUN) python tools/ci/check_secrets.py

check: docs-check repository-hygiene secret-scan backend-format-check backend-lint backend-typecheck backend-test \
	parser-contract-tests parser-benchmark-smoke \
	ingestion-integration admin-parser-golden-tests db-migration-test feedback-tests \
	frontend-format-check frontend-lint frontend-typecheck frontend-test frontend-build compose-config \
	web-e2e-smoke

dev:
	docker compose -f $(COMPOSE_FILE) up --build
