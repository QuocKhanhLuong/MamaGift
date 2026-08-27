# Supabase Existing-State Discovery Report

**Status:** `Live Supabase verification: NOT_RUN — BLOCKED_BY_CREDENTIALS`

---

## 1. Scope

- **Date:** 2026-08-27
- **Operating System / Platform:** macOS (darwin 25.2.0, arm64)
- **Repository:** `/Users/alvinluong/MamaGift` (branch `main`)
- **Objective:** Probe the local repository, environment variables, filesystem, and system toolchains for existing Supabase CLI installations, project configuration files, credentials, project references, and live database connectivity. Evaluate readiness for Phase 5 live Supabase verification.

---

## 2. Findings Table

| Probe Target | Command / Probe | Observed Result | Evidence / Details |
|---|---|---|---|
| Supabase CLI on PATH | `which supabase` | **Not installed** | Output: `supabase not found` (exit code 0 / command not found) |
| User config directory | `ls -la ~/.supabase` | **Absent** | Output: `No such file or directory` |
| Project config | `ls -la supabase/config.toml` | **Absent** | `supabase/` directory and `config.toml` do not exist |
| Environment variables | `env \| grep -E "SUPABASE\|DATABASE_URL\|POSTGRES"` | **All unset** | `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL`, `POSTGRES_*` are not set |
| Local environment file | `ls -la .env .env.example` | **`.env` absent** | Only `.env.example` exists, pointing to local default `localhost:5432` |
| Codebase references | `grep -ril supabase .` (excl. `.git`, `node_modules`) | **No project configs** | Matched only planning documents (`docs/superpowers/plans/...`) |
| Supabase Project Ref | Inspection of repo & environment | **Not discoverable** | No project identifier or organization link found on this machine |
| Docker Engine | `docker --version` | **Available** | `Docker version 29.7.2, build a7dcaa6` |
| Local PostgreSQL 16 + pgvector | `docker exec mamagift-pgvector-test psql ...` | **Running (PG 16 + pgvector 0.8.6)** | Running container `mamagift-pgvector-test` on `localhost:55432`, `vector` extension version 0.8.6 active |

---

## 3. Conclusion

The task brief indicates that an external Supabase project exists and is linked externally. However, **nothing in this repository, shell environment, or local filesystem can observe, identify, or authenticate with that Supabase project**.

In accordance with the repository hard rules (no fabricating credentials, project references, connection strings, or metrics):
- Live Supabase verification for Phase 5 is recorded as:
  **`NOT_RUN / BLOCKED_BY_CREDENTIALS`**
- Phase 5 development and integration proceed using the verified local PostgreSQL 16 + pgvector container.

---

## 4. What Phase 5 Verifies Instead

Phase 5 relies on a local PostgreSQL 16 + pgvector 0.8.6 environment running in Docker (`pgvector/pgvector:pg16` on port `55432`):

1. **Alembic Migrations:** Identical migration scripts (`0005_phase5_pgvector`, `0006_phase5_document_relations`) run against PostgreSQL 16, executing `CREATE EXTENSION IF NOT EXISTS vector` and column type changes.
2. **SQLAlchemy ORM Mapping:** Uses the `EmbeddingVector` type decorator, resolving dynamically to `pgvector.sqlalchemy.Vector(1024)` on PostgreSQL dialects.
3. **Dense Vector Search:** Employs the native pgvector `<=>` cosine distance operator for exact nearest neighbor queries.
4. **Relational Constraints & Joins:** Enforces the same composite foreign keys, CHECK constraints, and current-version join semantics.

Supabase runs stock PostgreSQL with the same `pgvector` extension, so the schema, the DDL in
each Alembic revision, and the SQL emitted by SQLAlchemy are the same artefacts in both
places. That is the basis for expecting the local result to carry over — it is not a
substitute for running it. Differences that local testing cannot rule out remain open until
the runbook below is executed: the project's PostgreSQL minor version, whether the database
role is permitted to `CREATE EXTENSION`, connection pooler behaviour (PgBouncer transaction
mode), the currently applied `alembic_version`, and which schemas the Data API exposes.
Until then this section states what was verified locally and nothing more.

---

## 5. Exact Operator Runbook to Complete Live Verification

When credentials become available, an operator can execute live verification against the Supabase project by following these steps:

### Step 1: Install Supabase CLI
```bash
brew install supabase/tap/supabase
```

### Step 2: Authenticate and Link Project
```bash
supabase login
supabase link --project-ref <PROJECT_REF>
```

### Step 3: Retrieve Connection Strings
From the Supabase Dashboard, navigate to **Project Settings > Database > Connection String**:
- **Direct Connection URL:** `postgresql://postgres:[YOUR-PASSWORD]@db.<PROJECT_REF>.supabase.co:5432/postgres`
- **Transaction Pooler URL (Port 6543):** `postgresql://postgres.<PROJECT_REF>:[YOUR-PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres`

### Step 4: Verify Database Version and Extensions
Connect via `psql` to check database version and verify `pgvector` is installed:
```bash
psql "<DIRECT_URL>" -c "select version();"
psql "<DIRECT_URL>" -c "select extname, extversion from pg_extension where extname = 'vector';"
```
*(If `vector` is not listed, enable it via Supabase Dashboard -> Database -> Extensions or run `CREATE EXTENSION IF NOT EXISTS vector;`)*

### Step 5: Check Current Migration State
```bash
psql "<DIRECT_URL>" -c "select version_num from alembic_version;"
```

### Step 6: Apply Alembic Migrations
Run Alembic against the Supabase direct connection string:
```bash
DATABASE_URL="<DIRECT_URL>" uv run alembic -c services/api/alembic.ini upgrade head
```

### Step 7: Verify Exposed Schemas in Dashboard
Navigate to **Project Settings > API > Exposed schemas**:
- Ensure private application tables (`documents`, `parse_runs`, `document_chunks`, `feedback_events`, `jobs`, `document_relations`) are protected by Row Level Security (RLS) or placed in schemas not exposed to PostgREST.

### Step 8: Probe Anonymous Data API Exposure
Run the anonymous read probe against the Supabase PostgREST endpoint:
```bash
curl -i -s -X GET "$SUPABASE_URL/rest/v1/documents?select=id" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Authorization: Bearer $SUPABASE_ANON_KEY"
```

**Evaluating the Exposure Result:**
- **SAFE:** HTTP `401`, `403`, or `404`, or a PostgREST error body. The anonymous role is
  refused before any row is considered.
- **UNSAFE:** any HTTP `200`, **including `200` with an empty array `[]`**. An empty array is
  not a pass: it means PostgREST accepted the anonymous read and the table simply had no rows
  matching. The same request against a populated table would return data. Treat `200 []` as
  exposure and fix it before release.
- **UNSAFE:** HTTP `200` returning records — direct, confirmed leakage.

Repeat this curl check for `parse_runs`, `document_chunks`, `feedback_events`, `jobs`, and `document_relations`.

---

## 6. Explicit Warnings and Safety Invariants

1. **DO NOT Create a Second Project:** Do not initialize a new Supabase project; verification must link to the designated project.
2. **DO NOT Run `supabase db reset`:** `db reset` wipes all remote database contents and drops schemas. Never run destructive resets against remote environments.
3. **DO NOT Overwrite Authoritative Data:** The Alembic migration `0005_phase5_pgvector` is designed to be non-destructive to authoritative records (`documents`, `parse_runs`, `feedback_events`, `jobs`).
4. **Vector Column Rebuild Behavior:** Migration `0005` safely drops and recreates the derived `document_chunks.embedding` column as `vector(1024)` and sets `embedding_version = NULL` / `embedding_model = NULL`. This cleanly signals the indexing worker (`needs_reindex`) to regenerate vectors without corrupting raw text or section metadata.
5. **No Secret Commits:** Never commit `.env` files, Supabase API keys (`anon` or `service_role`), or database passwords to version control.
