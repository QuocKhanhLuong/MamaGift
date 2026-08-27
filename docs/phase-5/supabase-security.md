# Supabase Direct-Data-Exposure Security Architecture & Verification

**Status:** `Live anonymous-exposure probe: NOT_RUN — BLOCKED_BY_CREDENTIALS`

---

## 1. Threat Model & Security Objective

MamaGift processes private administrative and legal family documents. The underlying storage architecture leverages PostgreSQL with `pgvector` (compatible with Supabase PostgreSQL). 

Supabase projects by default expose tables in exposed schemas (such as `public`) through the PostgREST Data API using the project's anonymous key (`SUPABASE_ANON_KEY` / `anon` role).

### The Threat
If any private application table—specifically:
- `documents` (raw metadata, filenames, sha256 checksums, storage URIs, document numbers, signers)
- `parse_runs` (full extracted canonical AST JSON structures, inspection results, quality reports)
- `document_chunks` (persisted text blocks, section hierarchy, page provenance, vector embeddings)
- `feedback_events` (user feedback, field corrections, annotations)
- `jobs` (background queue states, worker leases, internal processing error payloads)
- `document_relations` (cross-document citations and relationship mappings)

is readable by an anonymous client via the PostgREST endpoint, **private family documents and institutional records leak directly to the public internet with zero FastAPI authentication, authorization, or rate limiting involved**.

This threat represents a **RELEASE-BLOCKING** security vulnerability.

---

## 2. Two-Layer Verification Architecture

To provide continuous, defense-in-depth security guarantees in both automated CI environments (which lack production cloud credentials) and live deployment validation, MamaGift implements a two-layered test suite in [`tests/security/test_supabase_exposure.py`](file:///Users/alvinluong/MamaGift/tests/security/test_supabase_exposure.py).

```
┌────────────────────────────────────────────────────────────────────────┐
│ Layer 1: Structural & Static Guardrails (Always runs in CI / Local)    │
│  - No Supabase client libraries / keys in frontend bundle              │
│  - No direct PostgreSQL connection strings in web source               │
│  - All web network requests strictly route via api/client.ts           │
│  - 100% of SQLAlchemy models must be registered in PRIVATE_TABLES      │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Layer 2: Live Anonymous PostgREST Probe (Conditional Execution)        │
│  - Reads SUPABASE_URL and SUPABASE_ANON_KEY from environment           │
│  - Unset -> Skips with reason: NOT_RUN (BLOCKED_BY_CREDENTIALS)        │
│  - Set   -> Probes GET /rest/v1/{table}?select=*&limit=1               │
│  - Asserts HTTP 200 with JSON array (even empty []) is RELEASE BLOCKING│
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Layer 1: Structural & Static Guardrails

Layer 1 requires no external credentials and runs unconditionally on every `pytest` execution. It enforces the fundamental architectural principle: **The web frontend connects exclusively to the FastAPI backend; no browser-to-database channel may exist.**

### What Layer 1 Proves and Catches

| Test Function | What It Proves | What It Catches |
|---|---|---|
| `test_web_bundle_has_no_supabase_client` | The frontend codebase and package manifest contain zero Supabase client dependencies or configuration keys. | Accidental addition of `@supabase/supabase-js`, calls to `createClient(`, hardcoded `supabase.co` domains, `SUPABASE_ANON_KEY`, or `VITE_SUPABASE` environment variables in `apps/web/src/**` or `apps/web/package.json`. |
| `test_web_has_no_database_url` | No direct database connection strings exist in client-side code. | Developers inadvertently pasting `postgresql://`, `postgres://`, or `psycopg` connection URIs or drivers into frontend files. |
| `test_web_network_calls_go_through_the_api_client` | All client-side HTTP communication is centralized through the single transport layer [`apps/web/src/api/client.ts`](file:///Users/alvinluong/MamaGift/apps/web/src/api/client.ts). | Rogue `fetch(` or `axios` calls in React components/hooks that bypass structured error envelopes, telemetry, authentication, or retry logic. |
| `test_private_tables_are_enumerated` | The classified `PRIVATE_TABLES` security registry exactly matches the declared SQLAlchemy models in [`services/api/app/models.py`](file:///Users/alvinluong/MamaGift/services/api/app/models.py) (`Base.metadata.tables`). | Future migrations adding new database tables without explicit security review and classification. |

---

## 4. Layer 2: Live Anonymous Data API Probe

Layer 2 validates live cloud environments. When `SUPABASE_URL` and `SUPABASE_ANON_KEY` are provided in the environment, the probe issues HTTP GET requests against each private table:
```http
GET {SUPABASE_URL}/rest/v1/{table}?select=*&limit=1
apikey: {SUPABASE_ANON_KEY}
Authorization: Bearer {SUPABASE_ANON_KEY}
```

### Result Evaluation Matrix

| Status Code | Response Body | Classification | Assessment & Security Rationale |
|---|---|---|---|
| `401 Unauthorized` | Error JSON / text | **SAFE** | Anonymous key is rejected or unauthorized to access the API. |
| `403 Forbidden` | Error JSON / text | **SAFE** | PostgREST or PostgreSQL role permissions explicitly deny access to the table. |
| `404 Not Found` | Error JSON / text | **SAFE** | Table is not exposed in PostgREST schema cache. |
| `400 Bad Request` | PostgREST Error (e.g. `PGRST200`) | **SAFE** | PostgREST schema cache does not expose the table schema. |
| `200 OK` | `[{ ... records ... }]` | **UNSAFE (CRITICAL)** | **Direct Data Exposure.** Anonymous client can read private records directly from PostgreSQL. |
| `200 OK` | `[]` (empty array) | **UNSAFE (CRITICAL)** | **Direct Data Exposure.** An empty array proves the table is readable anonymously and merely has 0 rows currently. When rows are inserted, they will leak. |
| Network / Timeout | Connection failure | **FAIL** | Probe fails explicitly to prevent silent false positives. |

---

## 5. Current Verification State

As verified during repository discovery (documented in [`docs/phase-5/supabase-discovery.md`](file:///Users/alvinluong/MamaGift/docs/phase-5/supabase-discovery.md)):
- No live Supabase credentials (`SUPABASE_URL`, `SUPABASE_ANON_KEY`) or CLI configurations exist in this development environment.
- All structural tests in Layer 1 are **GREEN** (`4 passed`).
- Layer 2 live probe reports:
  ```text
  Live anonymous-exposure probe: NOT_RUN — BLOCKED_BY_CREDENTIALS
  ```

---

## 6. Remediation Runbook (If Live Probe Ever Fails)

If the live probe detects exposed tables upon supplying deployment credentials, execute the following remediation immediately:

### Option A: Restrict Exposed Schemas (Recommended)
In the Supabase Dashboard:
1. Navigate to **Project Settings > API**.
2. Under **Exposed schemas**, remove the schema containing application tables (e.g., ensure only intentional public views are listed, or move internal tables to a private schema such as `app` / `internal`).

### Option B: Enable Row Level Security (RLS) with Deny-by-Default
Execute SQL DDL against the PostgreSQL database to enable RLS on all private tables without granting permissions to `anon`:

```sql
-- Enable RLS on all private tables
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE parse_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;

-- If document_relations is present:
ALTER TABLE IF EXISTS document_relations ENABLE ROW LEVEL SECURITY;

-- Revoke all permissions on public tables from the anon role
REVOKE ALL ON TABLE documents FROM anon;
REVOKE ALL ON TABLE jobs FROM anon;
REVOKE ALL ON TABLE parse_runs FROM anon;
REVOKE ALL ON TABLE feedback_events FROM anon;
REVOKE ALL ON TABLE document_chunks FROM anon;
REVOKE ALL ON TABLE document_relations FROM anon;
```

> [!WARNING]
> **FastAPI Database Connection Invariant:**
> The FastAPI backend service connects using PostgreSQL connection strings (e.g., direct port 5432 or transaction pooler port 6543) authenticated as `postgres` or `service_role` (or a dedicated application role like `mamagift_api`). 
> 
> These administrative/service roles bypass Row Level Security by default (`BYPASSRLS`). **Hardening the anonymous PostgREST Data API by enabling RLS or removing schemas does NOT restrict or break the FastAPI service's database operations.** Under no circumstances should the FastAPI backend connect using the `anon` role.

---

## 7. Verification Commands

To run the security suite locally or in CI:

```bash
# Format and lint check
uv run ruff format tests/security
uv run ruff check tests/security

# Execute structural checks (Layer 1 passes, Layer 2 skips if credentials unset)
uv run pytest tests/security -q

# Execute full suite including live probe (when credentials available)
SUPABASE_URL="https://<project-ref>.supabase.co" \
SUPABASE_ANON_KEY="<anon-key>" \
uv run pytest tests/security -q
```
