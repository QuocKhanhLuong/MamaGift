UV ?= uv
UV_CACHE_DIR ?= $(CURDIR)/.uv-cache
# The shared packages are path-based, not installed, so tooling needs them on the path.
PYTHONPATH_PARTS = packages/contracts/python:packages/docpipe/python:packages/retrieval/python:packages/eval/python:packages/rag/python
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
	web-component-tests web-e2e-smoke feedback-tests retrieval-eval-tests \
	ai-worker-contract rag-unit-tests rag-eval-mini

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

# Phase 3.5 retrieval/evaluation-foundation gate.
retrieval-eval-tests:
	$(UV_RUN) pytest tests/unit/test_scope.py tests/unit/test_chunk_contract.py \
		tests/unit/test_legal_chunking.py tests/unit/test_plan_chunking.py \
		tests/unit/test_fallback_chunking.py tests/unit/test_chunk_builder.py \
		tests/unit/test_lexical_baseline.py tests/unit/test_budget.py \
		tests/unit/test_eval_schemas.py tests/unit/test_failure_taxonomy.py \
		tests/unit/test_document_type_slices.py tests/unit/test_eval_metrics.py \
		tests/golden/test_plan_chunking_golden.py -q

# Phase 4 AI-worker contract gate. CI never needs the home machine or a real model.
ai-worker-contract:
	$(UV_RUN) pytest services/ai-worker/tests tests/unit/test_chat_provider.py \
		tests/unit/test_embedding_provider.py -q

# Phase 4 grounded-RAG unit gate: providers, index, retrieval and indexing pipeline.
# Deterministic fakes only -- no model, GPU, network or private data.
rag-unit-tests:
	$(UV_RUN) pytest tests/unit/test_document_index.py tests/unit/test_lexical_retrieval.py \
		tests/unit/test_dense_retrieval.py services/api/tests/test_indexing_pipeline.py -q

# Phase 4 deterministic mini evaluation: retrieval harness, MamaGift answer-quality
# metrics, failure analysis, and the RAGAS adapter's unavailable path. No real model,
# no API key, no network -- RAGAS degrades to a typed UNAVAILABLE result.
rag-eval-mini:
	$(UV_RUN) pytest tests/unit/test_retrieval_harness.py tests/unit/test_qa_metrics.py \
		tests/unit/test_failure_analysis.py tests/unit/test_ragas_adapter.py -q


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
	ingestion-integration admin-parser-golden-tests db-migration-test feedback-tests retrieval-eval-tests \
	ai-worker-contract rag-unit-tests rag-eval-mini \
	frontend-format-check frontend-lint frontend-typecheck frontend-test frontend-build compose-config \
	web-e2e-smoke

dev:
	docker compose -f $(COMPOSE_FILE) up --build
