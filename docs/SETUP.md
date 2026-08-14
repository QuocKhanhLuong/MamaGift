# MamaGift local setup

This is the reproducible Phase 0 foundation. It provides a minimal React health screen, a FastAPI health endpoint, PostgreSQL migrations, and a contract-only fake AI worker. It does not implement document ingestion, OCR, parsing, RAG, or real LLM inference.

## Prerequisites

- Python 3.11 or newer;
- [uv](https://docs.astral.sh/uv/);
- Node.js 22 or newer and npm;
- Docker Desktop with Docker Compose v2.

## Fresh checkout

```bash
cp .env.example .env
uv sync --locked
npm ci --prefix apps/web
```

Run the deterministic Phase 0 gate:

```bash
make check
```

The backend migration smoke test uses an isolated SQLite database by default so it is deterministic without a running service. Compose starts PostgreSQL and applies the same Alembic migration against it.

## Compose development environment

```bash
docker compose -f infra/compose/docker-compose.yml config --quiet
docker compose -f infra/compose/docker-compose.yml up --build
```

Then open `http://localhost:5173`. The API health endpoint is available at `http://localhost:8000/health`.

Stop the environment with:

```bash
docker compose -f infra/compose/docker-compose.yml down
```

## Individual checks

```bash
make backend-format-check backend-lint backend-typecheck backend-test
make frontend-format-check frontend-lint frontend-typecheck frontend-test frontend-build
make docs-check repository-hygiene secret-scan compose-config
```

The lockfiles (`uv.lock` and `apps/web/package-lock.json`) are authoritative. Update them deliberately when dependencies change; CI uses locked installs.
