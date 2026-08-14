UV ?= uv
UV_CACHE_DIR ?= $(CURDIR)/.uv-cache
UV_RUN = UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) run
NPM ?= npm
COMPOSE_FILE ?= infra/compose/docker-compose.yml

.PHONY: setup backend-format-check backend-lint backend-typecheck backend-test \
	frontend-format-check frontend-lint frontend-typecheck frontend-test frontend-build \
	compose-config docs-check repository-hygiene secret-scan check dev

setup:
	UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) sync --locked
	$(NPM) ci --prefix apps/web

backend-format-check:
	$(UV_RUN) ruff format --check services/api services/ai-worker packages/contracts tools

backend-lint:
	$(UV_RUN) ruff check services/api services/ai-worker packages/contracts tools

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

compose-config:
	docker compose -f $(COMPOSE_FILE) config --quiet

docs-check:
	$(UV_RUN) python tools/ci/check_docs.py

repository-hygiene:
	$(UV_RUN) python tools/ci/check_repo_hygiene.py

secret-scan:
	$(UV_RUN) python tools/ci/check_secrets.py

check: docs-check repository-hygiene secret-scan backend-format-check backend-lint backend-typecheck backend-test \
	frontend-format-check frontend-lint frontend-typecheck frontend-test frontend-build compose-config

dev:
	docker compose -f $(COMPOSE_FILE) up --build
