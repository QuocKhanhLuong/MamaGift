# ADR-0001: Phase 0 application foundation

## Status

Accepted for Phase 0.

## Decision

- Use React + TypeScript + Vite for the web foundation.
- Use Python 3.11+ with FastAPI and Pydantic for the API.
- Use uv with a committed `uv.lock` for Python dependencies.
- Use npm with a committed `apps/web/package-lock.json` for JavaScript dependencies.
- Use PostgreSQL in Docker Compose and Alembic for schema migrations.
- Keep the AI-worker boundary typed with shared Pydantic contracts and a deterministic in-process fake implementation.

## Rationale

Vite keeps the Phase 0 web surface small and avoids prematurely implementing the document-first product shell. FastAPI/Pydantic matches the API-first architecture and provides explicit DTO validation. uv and npm lockfiles make fresh-machine setup deterministic. PostgreSQL is the documented production baseline, while the migration smoke test can use an isolated SQLite database when no external service is needed. The fake worker preserves the future service boundary without introducing OCR, parsing, retrieval, or model dependencies.

## Consequences

The Phase 0 web page is intentionally only a health screen. Document routes, upload flows, parser adapters, RAG, and real LLM integration remain future-phase work. A later phase may replace the fake worker implementation without changing the typed request/health contract.
