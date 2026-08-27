# ADR-003 — Supabase PostgreSQL + pgvector for production vector storage

- **Status:** ACCEPTED
- **Date:** 2026-08-27
- **Phase:** 5 — Cross-document institutional memory
- **Supersedes:** nothing
- **Depends on:** ADR-0001 (Phase 0 application foundation)

## Context

Phase 4 implemented single-document retrieval and grounded question answering:
- Document chunk embeddings were stored in `document_chunks.embedding` as SQLAlchemy `JSON`
  (`sa.JSON`).
- `SqlDocumentIndex.search_dense`
  (`packages/retrieval/python/mamagift_retrieval/index/sql_index.py`) loaded every scoped
  row for a given document into Python memory and computed cosine similarity in a pure-Python
  loop.
- In-memory computation is acceptable inside a single document (~10–100 chunks). Across an
  entire archive of administrative documents (thousands to tens of thousands of chunks),
  loading all vectors into Python for a linear scan is `O(corpus)` in memory and latency
  per query, which is unsustainable for multi-document institutional memory.

Key technical constraints and verified baseline facts:
1. **Embedding dimension is 1024.** Verified across `BgeM3EmbeddingProvider`
   (`packages/retrieval/python/mamagift_retrieval/providers/bge_m3.py`) and
   `FakeEmbeddingProvider` (`fake_embedding.py`).
2. **Relational metadata filtering & current-version isolation.** Phase 5 cross-document
   retrieval requires strict relational joins against `documents` and `parse_runs` to ensure
   metadata filtering (`document_type`, `issuer`, `issued_date`) and current-version isolation
   (`parse_runs.is_current = true AND documents.current_parse_run_id = parse_runs.id`).
3. **Application and security boundary.** The architecture remains
   `React -> FastAPI -> SQLAlchemy -> PostgreSQL`. `supabase-py` and PostgREST are
   explicitly **not** adopted; FastAPI remains the sole product, business logic, and security
   boundary. Alembic remains the single source of truth for database schema migrations.
   Supabase Auth and Supabase Storage remain out of scope.

## Decision

**Production vector storage is PostgreSQL with the `pgvector` extension enabled, accessed
through the existing SQLAlchemy and Alembic stack. Status: ACCEPTED.**

Specifically:
1. `document_chunks.embedding` uses PostgreSQL's native `vector(1024)` data type in
   production and staging PostgreSQL environments.
2. Vector similarity searches are executed directly in SQL via `pgvector` distance operators
   (exact `<=>` cosine distance / `<->` L2 distance), combined in the same query with
   metadata filters and current-version relational joins.
3. FastAPI and SQLAlchemy manage all database interactions. No external vector-specific
   service or direct client library is introduced.

## Options considered

### 1. Keep JSON column + Python in-memory cosine scan
- **Description:** Retain `document_chunks.embedding` as `sa.JSON` and load candidate rows
  into Python to compute cosine similarity.
- **Why rejected:** Linear scan per query over the whole archive (`O(corpus)` memory
  and compute). Cannot leverage database indexing, and vector dimension is completely
  unenforced by the database schema.

### 2. External vector database (Qdrant / Weaviate / pinned cloud service)
- **Description:** Ship embeddings and chunk payloads to a separate specialized vector database.
- **Why rejected:**
  - Introduces a second datastore to operate, back up, migrate, and keep transactionally
    consistent with `parse_runs` and `documents`.
  - Loses the relational `JOIN` to `documents` and `parse_runs` that Phase 5's metadata
    filters (`document_type`, `issuer`, `issued_date`) and current-version guard
    (`parse_runs.is_current = true AND documents.current_parse_run_id = parse_runs.id`)
    depend on.

### 3. pgvector in the existing PostgreSQL
- **Description:** Enable `pgvector` in the existing PostgreSQL instance and store vectors in
  `vector(1024)` columns.
- **Why accepted (ACCEPTED):**
  - One datastore, one ACID transaction boundary, one backup and restore lifecycle.
  - Relational metadata filtering and current-version isolation remain ordinary SQL joins
    executed atomically alongside vector distance operations.
  - `vector(1024)` enforces dimension integrity at the column level.
  - Supabase supports the `pgvector` extension natively on standard PostgreSQL instances.

## Consequences

1. **Dialect abstraction (`TypeDecorator`):**
   `document_chunks.embedding` becomes `vector(1024)` on PostgreSQL and stays `JSON` on
   SQLite via a custom `TypeDecorator` (`services/api/app/vector_type.py`). This preserves the
   fast, dependency-free SQLite unit test suite without requiring PostgreSQL/pgvector for unit
   tests.

2. **Destructive migration with automatic re-indexing:**
   Migration `0005_phase5_pgvector` drops the existing JSON `embedding` column, creates the
   new `vector(1024)` column, and resets `embedding_version = NULL` and `embedding_model = NULL`.
   - Embeddings are derived data; authoritative tables (`documents`, `parse_runs` including
     canonical ASTs, `feedback_events`, and `jobs`) are completely untouched.
   - Resetting `embedding_version` triggers `needs_reindex()` during normal worker operation,
     safely re-computing embeddings on the next indexing pass.
   - Re-embedding is strictly safer than in-place numeric conversion, which risks data
     corruption, type conversion edge cases, or migration timeouts on large datasets.

3. **Exact search only, for now (no ANN index yet):**
   No HNSW or IVFFlat approximate nearest neighbor (ANN) index is created initially.
   - **Explicit rule:** An ANN index will only be added after measured P95 query latency on the
     real corpus exceeds the latency budget.
   - **Rationale:** ANN algorithms trade recall for speed, whereas Phase 5 enforces strict
     zero-leakage and precision gates that require exact recall. No latency claim is made
     here in advance of measurement: whether exact `<=>` scan with metadata filtering is fast
     enough at the real corpus size is a question for the benchmark below, not for this ADR.
   - **Benchmark authority:** `tools/eval/archive_latency.py` is the benchmark that would
     justify revisiting an ANN index.

4. **Downgrade safety:**
   `alembic downgrade 0004_phase4_chunk_index` drops the `vector(1024)` column, restores the
   `JSON` column, and clears `embedding_version`. The `vector` extension itself is **not**
   dropped on downgrade, because a shared extension may back unrelated objects on the user's
   existing PostgreSQL or Supabase project.

## Live verification status

- **Environment probe findings:** As documented in `docs/phase-5/supabase-discovery.md`, no
  Supabase project ref, credentials, configuration file (`supabase/config.toml`), or
  `supabase` CLI were reachable from the development machine.
- **Testing boundary:** All Phase 5 vector storage and retrieval capabilities were verified
  against local PostgreSQL 16 + pgvector 0.8.6 running in Docker.
- **Verification status:** Live Supabase cloud project verification is recorded honestly as
  `NOT_RUN / BLOCKED_BY_CREDENTIALS`.

## References

- `docs/superpowers/plans/2026-08-27-phase-5-cross-document-institutional-memory.md`
- `docs/decisions/ADR-0001-phase0-stack.md`
- `docs/phase-5/supabase-discovery.md`
- `services/api/app/vector_type.py`
- `services/api/alembic/versions/0005_phase5_pgvector.py`
- `packages/retrieval/python/mamagift_retrieval/index/sql_index.py`
- `packages/retrieval/python/mamagift_retrieval/providers/bge_m3.py`
- `tools/eval/archive_latency.py`
