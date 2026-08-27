# Phase 5 — Cross-document institutional memory

Plan date: 2026-08-27
Base HEAD: `0b26b97ecb3349e6075489283b119d5f6208c316` (`main`, identical to `origin/main`)
Planner / architect / integrator: Claude
Implementation workers: Agy (`agy --dangerously-skip-permissions --model gemini-3.7-flash-high --effort high`)

---

## 1. Actual starting state

### 1.1 Repository reconciliation (STEP 0 result)

| Check | Result |
| --- | --- |
| `git status` | clean, no untracked files |
| `HEAD` | `0b26b97` — matches the expected remote SHA exactly |
| `origin/main` | `0b26b97` — no local unpushed commits, no divergence |
| Local branches | `main` only |
| Remote branches | `origin/main`, `origin/eval/real-pdf-batch-01` (`49d3cb6`, historical eval evidence, not a stale orchestration branch) |
| Worktrees | one: `/Users/alvinluong/MamaGift` on `main` |
| **Unpushed Phase 5 implementation** | **NONE.** No archive index, no pgvector, no `document_relations`, no archive QA endpoint, no archive UI exists anywhere in the tree. |

Phase 5 is therefore a from-scratch implementation, not a reconstruction.

### 1.2 What Phase 4 actually left behind (verified by reading the code, not the docs)

**Retrieval package** (`packages/retrieval/python/mamagift_retrieval/`)

- `scope.py` — `EvidenceScope` already carries an `archive_scope: bool` flag and
  `scope_matches` already implements the archive branch (`archive_scope=True` skips the
  `document_id` equality check while still enforcing `family_id`, `user_id`, `thread_id`,
  and any pinned `document_version` / `parse_run_id`). **Phase 5 does not need to change
  this function.** No production caller sets `archive_scope=True` today.
- `chunk.py` — `Chunk` already declares optional `document_type`, `document_number`,
  `issuer`, `issued_date`. These are **never populated** today: `SqlDocumentIndex._row_to_chunk`
  leaves them `None` and `document_chunks` has no such columns.
- `index/protocol.py` — `DocumentIndex` Protocol, five methods, plus the module constant
  `AUTHORITATIVE_FAMILY_ID = "mamagift"`.
- `index/sql_index.py` — `SqlDocumentIndex`. Imports `app.models.DocumentChunk` (the
  retrieval package already depends on the API service's models; Phase 5 keeps that
  coupling rather than inventing a second mapping). `search_dense` loads **every** scoped
  row into Python and computes cosine in a pure-Python loop. `search_lexical` is set-overlap,
  not BM25. Both hard-require `scope.document_id`; neither can go global by accident today,
  but neither explicitly rejects `archive_scope=True`.
- `search/lexical.py` — a real Okapi BM25 (`BM25Index`, k1=1.5, b=0.75) that operates over an
  **in-memory** chunk sequence. `BM25LexicalRetriever` wrapping a `DocumentIndex` silently
  degrades to the index's set-overlap `search_lexical`; the SQL path is not BM25 today.
- `search/vi_tokenize.py` — already strong for Phase 5's exact-identifier requirement:
  preserves `12/KH-UBND`-shaped document numbers as indivisible tokens, emits `điều_7`,
  `khoản_2`, `điểm_a`, `phụ_lục` compounds, and normalises both `31/03/2026` and
  `ngày 31 tháng 03 năm 2026`. **Reused unchanged.**
- `search/fusion.py` — rank-only RRF (`RRF_K = 60`), raw scores deliberately never summed.
  `_validate_fusion_scope` **explicitly raises on `archive_scope`** and requires a pinned
  document/version/parse-run.
- `rerank/protocol.py` — `validate_rerank_candidates` **requires every candidate to share one
  `(document_id, document_version, parse_run_id)`**. Structurally incompatible with archive
  retrieval.
- `evidence/assembler.py` — `assemble_evidence` writes the whole candidate text into the
  single `selected_document` budget category. Already tolerates archive scope through
  `scope_matches`, but has no per-document fairness.
- `evidence/expansion.py` — ancestor-only expansion, max depth 3, never traverses siblings.
  Correct for Phase 5's Kế hoạch gate and reused unchanged.
- `budget.py` — five named categories including an unused `archive_semantic_chars`.

**RAG package** (`packages/rag/python/mamagift_rag/`)

- `service.py` — `QaService._validate_request_scope` **hard-rejects `archive_scope`** and
  requires document_id + version + parse_run_id. This is the guarantee that selected-document
  QA stays incapable of cross-document retrieval; Phase 5 must not weaken it.
- `validation.py` — `parse_and_validate_answer` enforces the citation allow-list against the
  `EvidenceSet`: unknown `citation_id`, mismatched `document_id`, unknown page, unknown source
  block, or a quote absent from the evidence text all downgrade the answer to `failed`.
  Already per-item and document-aware, so it is **reused for archive answers unchanged**.
- `prompt.py` / `injection.py` — untrusted-data delimiters, HTML escaping, and a Vietnamese
  system policy that already forbids widening retrieval scope.

**API service** (`services/api/app/`)

- `models.py` — `document_chunks.embedding` is `sa.JSON`, nullable, alongside
  `embedding_model` / `embedding_version`. `ParseRun.is_current` and
  `Document.current_parse_run_id` both exist and are the two independent facts that define
  the current version.
- `alembic/versions/0004_phase4_chunk_index.py` — latest revision. `alembic/env.py` reads
  `DATABASE_URL` from the environment. No runtime `create_all` anywhere.
- `indexing.py` — `index_parse_run` / `index_document`, with `needs_reindex(stats, provider)`
  returning `True` when chunks are missing, partially embedded, **or on a stale
  `embedding_version`**. This is the hook that makes a destructive-and-reindex pgvector
  migration safe.
- `routers/qa.py` — `POST /api/v1/documents/{id}/qa`, resolving the scope from
  `Document.current_parse_run_id` → `ParseRun` and refusing when `is_current` is false.

**Web** (`apps/web/`) — routes `/dang-nhap`, `/van-ban`, `/van-ban/:documentId`.
`AssistantPanel` is document-gated (`document?.status === "READY"`), `useQa` is keyed to one
`documentId`. No archive-level assistant exists.

**Tests / CI** — pytest runs on **SQLite** by default; `services/api/tests/test_migrations.py`
already honours `MAMAGIFT_TEST_DATABASE_URL`, and CI's `backend-test` / `db-migration-test`
jobs already start a PostgreSQL service. That env var is the seam Phase 5's pgvector
integration tests hang off.

### 1.3 Verified facts that constrain the design

1. **Embedding dimension is 1024.** `BgeM3EmbeddingProvider.__init__(dimension: int = 1024)`
   and `FakeEmbeddingProvider.__init__(dimension: int = 1024)`. Frozen as `EMBEDDING_DIM = 1024`.
2. **`pgvector` is not a dependency.** `pyproject.toml` has no pgvector; `uv.lock` must be
   regenerated by Claude, not by a worker.
3. **No Supabase artefact exists in this repository or environment.** `grep -ril supabase`
   over the whole tree returns nothing; there is no `supabase/` directory, no
   `supabase/config.toml`, no `~/.supabase`, no `SUPABASE_*` / `DATABASE_URL` environment
   variable, and the `supabase` CLI is not installed. See §8.
4. **Docker is available** (server 29.7.2), so a real PostgreSQL 16 + pgvector container is
   reachable locally for integration tests.

---

## 2. Architecture

```
                 user archive question + ArchiveFilter
                                │
                                ▼
              SqlArchiveIndex — relational metadata filter
              (documents ⋈ parse_runs ⋈ document_chunks)
              HARD JOIN: parse_runs.is_current = true
                     AND documents.current_parse_run_id = parse_runs.id
                                │
                 ┌──────────────┴──────────────┐
                 ▼                             ▼
        archive lexical (BM25 over        pgvector dense
        tokenize_vi, identifier-aware)    (<=> operator, exact)
                 │                             │
                 └──────────────┬──────────────┘
                                ▼
              archive_reciprocal_rank_fusion (RRF_K = 60, rank-only)
                                ▼
              archive reranker (existing Reranker protocol,
              archive-aware candidate validation)
                                ▼
              current-version guard (independent re-check
              against the allow-list built pre-retrieval)
                                ▼
              multi-document evidence assembler
              (per-document cap + archive_semantic budget)
                                ▼
              existing build_grounded_prompt + grounded LLM
                                ▼
              existing parse_and_validate_answer allow-list
              + archive document allow-list check
                                ▼
              ArchiveQaAnswer: citations grouped by document
                                ▼
              web: click citation → /van-ban/:id?page=N&block=B
```

**One RAG stack, two scopes.** Every box above is either a Phase 4 component reused verbatim
(`tokenize_vi`, `BM25Index` scoring maths, `RRF_K`, `Reranker`, `expand_evidence`,
`build_grounded_prompt`, `wrap_untrusted_document`, `parse_and_validate_answer`) or a
scope-parallel sibling that shares the same core. No second reranker, no second RRF formula,
no second prompt, no second citation validator.

### 2.1 The critical separation

`DocumentIndex` / `QaService` (single document) and `ArchiveIndex` / `ArchiveQaService`
(many current documents) are **disjoint types with mutually exclusive scope guards**:

| | rejects `archive_scope=True` | rejects `archive_scope=False` | requires `document_id` | requires `parse_run_id` |
| --- | --- | --- | --- | --- |
| `SqlDocumentIndex` (all methods) | **yes — added in B0** | no | yes | yes or version |
| `QaService._validate_request_scope` | yes (already) | no | yes | yes |
| `reciprocal_rank_fusion` | yes (already) | no | yes | yes |
| `SqlArchiveIndex` (all methods) | no | **yes** | **must be `None`** | **must be `None`** |
| `ArchiveQaService._validate_request_scope` | no | **yes** | **must be `None`** | **must be `None`** |
| `archive_reciprocal_rank_fusion` | no | **yes** | **must be `None`** | **must be `None`** |

Selected-document QA cannot reach archive retrieval because `QaService` refuses an archive
scope and `SqlDocumentIndex` refuses to run without a `document_id`. Archive QA cannot
silently collapse into "one global DocumentIndex" because `SqlArchiveIndex` refuses a scope
that pins a `document_id`. Both directions are tested (G5).

---

## 3. Frozen contracts

Everything in this section is frozen before any worker starts. A worker that needs a change
here escalates to Claude; it does not edit the contract.

### 3.1 Constants

```python
# mamagift_retrieval.archive.constants
EMBEDDING_DIM = 1024                 # verified against BgeM3EmbeddingProvider/FakeEmbeddingProvider
ARCHIVE_LEXICAL_TOP_K = 50
ARCHIVE_DENSE_TOP_K = 50
ARCHIVE_RERANK_TOP_K = 12
ARCHIVE_MAX_DOCUMENTS = 8            # distinct documents allowed into one evidence set
ARCHIVE_PER_DOCUMENT_CHAR_CAP = 3_000
ARCHIVE_EVIDENCE_BUDGET_CHARS = 16_000   # spent from EvidenceBudget.archive_semantic_chars
# RRF_K is NOT redefined; mamagift_retrieval.search.fusion.RRF_K (=60) is imported.
```

### 3.2 `ArchiveFilter` — the only metadata filter shape

```python
# mamagift_retrieval/archive/filters.py
class ArchiveFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_ids: list[str] | None = None       # None = no restriction; [] = match nothing
    document_types: list[str] | None = None
    document_numbers: list[str] | None = None    # matched on normalised form, see 3.3
    issuers: list[str] | None = None             # case-insensitive exact match
    issued_date_from: date | None = None         # inclusive
    issued_date_to: date | None = None           # inclusive
    include_requires_review: bool = True         # False drops documents.requires_user_review
```

Invariants, enforced in a validator and tested:
- `issued_date_from > issued_date_to` raises.
- An **empty list** means "match nothing", never "match everything". A worker that treats
  `[]` as unfiltered is rejected.
- There is **no** field that disables current-version filtering. Current-version isolation is
  not a filter; see 3.4.

### 3.3 Identifier normalisation (frozen)

```python
def normalize_identifier(value: str) -> str:
    """NFC-normalise, strip, collapse internal whitespace around '/' and '-', uppercase."""
```
`" 19 / 2026 / TT-BGDĐT "` → `"19/2026/TT-BGDĐT"`. Used for `ArchiveFilter.document_numbers`
matching and for the exact-identifier boost (C5). Query-side identifier extraction reuses
`mamagift_retrieval.search.vi_tokenize` regexes; **no second tokenizer is written.**

### 3.4 Current-version isolation (hard invariant, not a filter)

Every `SqlArchiveIndex` query builds its candidate set from exactly this join:

```sql
FROM document_chunks c
JOIN parse_runs p
  ON p.id = c.parse_run_id
 AND p.document_id = c.document_id
 AND p.version = c.document_version
JOIN documents d
  ON d.id = c.document_id
WHERE p.is_current IS TRUE
  AND d.current_parse_run_id = p.id
```

Two independent facts (`parse_runs.is_current` and `documents.current_parse_run_id`) must
agree. A row satisfying only one is excluded. There is no code path, parameter, or filter
that omits either predicate.

### 3.5 `ArchiveIndex` protocol

```python
# mamagift_retrieval/archive/protocol.py
class ArchiveDocumentRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    parse_run_id: str
    document_version: int
    document_type: str | None
    document_number: str | None
    title: str | None
    issuer: str | None
    issued_date: date | None
    requires_user_review: bool

class ArchiveIndexStats(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_documents: int = 0
    total_chunks: int = 0
    embedded_chunks: int = 0
    embedding_model: str | None = None
    embedding_version: str | None = None

@runtime_checkable
class ArchiveIndex(Protocol):
    def current_documents(self, scope: EvidenceScope, filters: ArchiveFilter | None = None) -> list[ArchiveDocumentRef]: ...
    def search_dense(self, scope: EvidenceScope, query_vector: list[float], top_k: int, filters: ArchiveFilter | None = None) -> list[ScoredChunk]: ...
    def search_lexical(self, scope: EvidenceScope, query: str, top_k: int, filters: ArchiveFilter | None = None) -> list[ScoredChunk]: ...
    def stats(self, scope: EvidenceScope, filters: ArchiveFilter | None = None) -> ArchiveIndexStats: ...
```

`ScoredChunk` is the **existing** `mamagift_retrieval.index.entries.ScoredChunk`, re-exported
via `mamagift_retrieval.search.types`. No new ranking type is introduced. Archive results
populate the `Chunk.document_type / document_number / issuer / issued_date` fields from the
joined `documents` row — relational metadata, never duplicated into the vector blob.

Scope guard, identical in all four methods:
```python
def _validate_archive_scope(scope: EvidenceScope) -> None:
    if scope.family_id != AUTHORITATIVE_FAMILY_ID: raise ValueError(...)
    if not scope.archive_scope:      raise ValueError("archive index requires archive_scope=True")
    if scope.document_id is not None: raise ValueError("archive scope must not pin document_id")
    if scope.parse_run_id is not None: raise ValueError("archive scope must not pin parse_run_id")
    if scope.document_version is not None: raise ValueError("archive scope must not pin document_version")
```

### 3.6 pgvector storage type

```python
# services/api/app/vector_type.py
class EmbeddingVector(TypeDecorator[list[float] | None]):
    """vector(1024) on PostgreSQL, JSON elsewhere. Same Python value either way."""
    cache_ok = True
    impl = JSON
    def __init__(self, dim: int = EMBEDDING_DIM) -> None: ...
    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(pgvector.sqlalchemy.Vector(self.dim))
        return dialect.type_descriptor(JSON())
```

`DocumentChunk.embedding` changes from `mapped_column(JSON, nullable=True)` to
`mapped_column(EmbeddingVector(EMBEDDING_DIM), nullable=True)`. **The Python-side value stays
`list[float] | None`** — no caller in `indexing.py`, `sql_index.py`, or the tests changes.

### 3.7 `document_relations` table

```
id                     String(64)  PK
source_document_id     String(64)  FK documents.id ON DELETE CASCADE, NOT NULL, indexed
source_parse_run_id    String(64)  NOT NULL
source_document_version Integer    NOT NULL
                       composite FK -> parse_runs(id, document_id, version) ON DELETE CASCADE
source_block_ids       JSON        NOT NULL, non-empty  (provenance, enforced in code + test)
page_numbers           JSON        NOT NULL, non-empty
relation_type          String(32)  NOT NULL  in {references, amends, replaces, supersedes}
target_document_id     String(64)  FK documents.id ON DELETE SET NULL, NULLABLE
target_document_number String(128) NULLABLE  (normalised form, 3.3)
target_raw_text        Text        NOT NULL  (verbatim source span, never synthesised)
confidence             Float       NOT NULL  0.0..1.0
review_state           String(32)  NOT NULL  in {unverified, confirmed, rejected}, default unverified
created_at             DateTime(tz) NOT NULL server_default now()

CHECK (target_document_id IS NOT NULL OR target_document_number IS NOT NULL)
UNIQUE (source_parse_run_id, relation_type, target_document_number, target_document_id)
```

Rules frozen here and tested in C7/E4/G6:
- Relations are extracted **deterministically from canonical block text by regex**, never by
  the LLM. There is no code path where a model response creates a relation row.
- A relation naming a document not present in the archive is stored with
  `target_document_id = NULL` and its normalised `target_document_number`. **No `documents`
  row is ever created to satisfy a relation.**
- `review_state` defaults to `unverified`. The answer surface labels unverified relations as
  such and never states supersession as fact from an unverified row.
- Freshness never writes or implies a relation. `issued_date` ordering answers "newest";
  legal control requires a `replaces` / `supersedes` / `amends` row with provenance.

### 3.8 `POST /api/v1/archive/qa`

Request (`ArchiveQaRequest`, `extra="forbid"`):
```json
{
  "question": "Văn bản mới nhất liên quan tới tuyển sinh là văn bản nào?",
  "filters": {
    "document_ids": null, "document_types": ["Thông tư"], "document_numbers": null,
    "issuers": null, "issued_date_from": "2026-01-01", "issued_date_to": "2026-12-31",
    "include_requires_review": true
  }
}
```
`filters` is optional; `question` is `min_length=1, max_length=2000`.

Response (`ArchiveQaAnswer`, `extra="forbid"`) — **a superset of `QaAnswer`, sharing its
`Citation`, `RetrievalRef`, `ModelRef` and `status` literal unchanged**:
```json
{
  "answer": "…",
  "status": "answered|insufficient_evidence|ai_worker_unavailable|failed",
  "citations": [ Citation, … ],
  "document_groups": [
    { "document_id": "doc_1", "document_number": "19/2026/TT-BGDĐT", "title": "…",
      "document_type": "Thông tư", "issuer": "…", "issued_date": "2026-03-31",
      "document_version": 2, "parse_run_id": "prun_…",
      "citation_ids": ["c1", "c3"] }
  ],
  "relations": [
    { "relation_type": "replaces", "review_state": "unverified", "confidence": 0.9,
      "source_document_id": "doc_2", "target_document_id": "doc_1",
      "target_document_number": "57/QĐ-UBND", "citation_ids": ["c4"] }
  ],
  "retrieval": { "query_id": "qry_…" },
  "model": { "provider": "…", "model": "…", "version": "…" }
}
```
- `citations` is the flat allow-list-validated list, byte-identical in shape to Phase 4.
- `document_groups` is a **pure regrouping** of `citations` — every `citation_id` in a group
  appears in `citations`, every citation appears in exactly one group, and every
  `document_id` in a group is in the retrieved current-version document set. All three are
  asserted server-side before the response leaves the router (D4); a violation is a 500
  `qa_scope_violation`, never a returned answer.
- `relations` is empty unless an evidence-backed `document_relations` row covers a cited
  document; each entry names citations already in `citations`.

Error codes reuse the existing `services/api/app/errors.py` catalogue:
`ai_worker_unavailable` (503), `qa_scope_violation` (500), and a new
`archive_not_indexed` (409, retryable) when no current document survives the filters.

### 3.9 Web contract

- Route `/tro-ly` — archive assistant, entry point in `Sidebar`.
- Citation click → `/van-ban/:documentId?trang=<page>&khoi=<blockId>`; `DocumentPage` reads
  those params and drives the existing `SourceViewer`. Query-param names are frozen here so
  F3/F4 and G3 agree.
- `useArchiveQa` mirrors `useQa`'s state machine (`idle | loading | success | error`) and its
  abort-on-new-question rule.

---

## 4. Dependency DAG

```
A3 pgvector migration ──┐
A4 EmbeddingVector type ┘─→ A5 local PG+pgvector test infra ─→ (all PG integration tests)
A1 Supabase discovery ──────→ A2 ADR ──→ A6 exposure/security test
B0 DocumentIndex archive-scope hardening (Claude) ─→ B1 ArchiveIndex protocol
                                                       │
      ┌────────────────────────────────────────────────┼──────────────┐
      ▼                    ▼                ▼          ▼              ▼
B2 pgvector dense    B3 archive lexical  B4 filters  B5 current-ver  B6/B7 lifecycle
      └────────────────────┴────────────────┴──────────┴──────────────┘
                                   ▼
      C1 hybrid orchestration ← C2 archive RRF ← C3 archive rerank validation
                                   │
                  ┌────────────────┼────────────────┐
                  ▼                ▼                ▼
             C4 freshness     C5 identifiers   C6 relation model → C7 extraction
                                   ▼
      D3 multi-doc assembler → D1 ArchiveQaService → D2 endpoint → D4 grouping
                                   │                       └→ D5 abstention, D6 injection
                                   ▼
      E1 corpus → E2 metrics → E3/E4/E5/E6 → E7 baseline → E8 RAGAS → E9 latency
                                   ▼
      F1 entry → F2 workspace → F3 grouped citations → F4 navigation → F5 states → F6 responsive
                                   ▼
      G1..G9 end-to-end
```

Wave gates: **B cannot start until A3+A4+A5 are integrated and green. C cannot start until B
is integrated. D cannot start until C1–C3. F needs D2's frozen response shape (available from
§3.8 immediately, so F1/F2 can start in parallel with D against the frozen contract). G runs
last.**

---

## 5. Agy worker ownership map (exclusive file ownership)

No two concurrently-running workers may touch the same file. Claude owns every shared/barrel
file (`__init__.py`, `pyproject.toml`, `uv.lock`, `Makefile`, `.github/workflows/ci.yml`,
`docs/PHASE_STATUS.md`) and performs all merges into them.

| Task | Owns (exclusive) | Depends on |
| --- | --- | --- |
| **A1** | `docs/phase-5/supabase-discovery.md` | — |
| **A2** | `docs/decisions/ADR-003-supabase-postgres-pgvector.md` | A1 |
| **A3** | `services/api/alembic/versions/0005_phase5_pgvector.py` | A4 contract (frozen §3.6) |
| **A4** | `services/api/app/vector_type.py`, `tests/unit/test_vector_type.py` | — |
| **A5** | `tests/integration/conftest.py`, `tests/integration/test_pgvector_infra.py`, `infra/compose/docker-compose.test.yml` | — |
| **A6** | `tests/security/test_supabase_exposure.py`, `docs/phase-5/supabase-security.md` | A1 |
| **B0** | `packages/retrieval/.../index/sql_index.py` (guard only) — **Claude** | — |
| **B1** | `packages/retrieval/.../archive/protocol.py`, `archive/constants.py`, `tests/unit/test_archive_protocol.py` | B0 |
| **B2** | `packages/retrieval/.../archive/dense.py`, `tests/integration/test_archive_dense_pgvector.py` | B1, A3/A4 |
| **B3** | `packages/retrieval/.../archive/lexical.py`, `tests/unit/test_archive_lexical.py` | B1 |
| **B4** | `packages/retrieval/.../archive/filters.py`, `tests/unit/test_archive_filters.py` | B1 |
| **B5** | `packages/retrieval/.../archive/sql_archive_index.py`, `tests/unit/test_archive_current_version.py` | B1–B4 |
| **B6** | `services/api/app/archive_indexing.py`, `services/api/tests/test_archive_indexing.py` | B5 |
| **B7** | `services/api/tests/test_archive_index_isolation.py` | B6 |
| **C1** | `packages/retrieval/.../archive/retriever.py`, `tests/unit/test_archive_retriever.py` | B5, C2, C3 |
| **C2** | `packages/retrieval/.../search/fusion.py` (add archive entry point), `tests/unit/test_archive_fusion.py` | B1 |
| **C3** | `packages/retrieval/.../rerank/protocol.py` (add archive validator), `tests/unit/test_archive_rerank.py` | B1 |
| **C4** | `packages/retrieval/.../archive/freshness.py`, `tests/unit/test_freshness.py` | B5 |
| **C5** | `packages/retrieval/.../archive/identifiers.py`, `tests/unit/test_identifiers.py` | B3 |
| **C6** | `services/api/app/models.py` (relations model only), `services/api/alembic/versions/0006_phase5_document_relations.py` | A3 |
| **C7** | `packages/docpipe/.../relations.py`, `services/api/app/relation_extraction.py`, `tests/unit/test_relation_extraction.py` | C6 |
| **D1** | `packages/rag/.../archive_service.py`, `tests/unit/test_archive_qa_service.py` | C1, D3 |
| **D2** | `services/api/app/routers/archive.py`, `services/api/app/schemas.py` (archive schemas only), `services/api/tests/test_archive_qa_api.py` | D1 |
| **D3** | `packages/retrieval/.../evidence/archive_assembler.py`, `tests/unit/test_archive_assembler.py` | B1 |
| **D4** | `packages/rag/.../archive_grouping.py`, `tests/unit/test_citation_grouping.py` | D1 |
| **D5** | `tests/unit/test_archive_abstention.py` | D1 |
| **D6** | `tests/unit/test_archive_injection.py` | D1 |
| **E1** | `tests/fixtures/archive/**` (canonical JSON corpus + `cases.jsonl`) | — |
| **E2** | `packages/eval/.../archive_harness.py`, `tests/unit/test_archive_harness.py` | E1 |
| **E3** | `packages/eval/.../freshness_eval.py`, `tests/unit/test_freshness_eval.py` | E1, C4 |
| **E4** | `packages/eval/.../relation_eval.py`, `tests/unit/test_relation_eval.py` | E1, C7 |
| **E5** | `tests/unit/test_archive_plan_eval.py` | E1, E2 |
| **E6** | `tests/unit/test_archive_leak_eval.py` | E1, E2 |
| **E7** | `tools/eval/archive_baseline.py`, `docs/eval/phase-5-baseline.md` | E2 |
| **E8** | `packages/eval/.../archive_ragas.py`, `tests/unit/test_archive_ragas.py` | E1 |
| **E9** | `tools/eval/archive_latency.py`, `docs/eval/phase-5-latency.md` | E2 |
| **F1** | `apps/web/src/components/shell/Sidebar.tsx`, `apps/web/src/pages/ArchiveAssistantPage.tsx` | §3.9 |
| **F2** | `apps/web/src/components/assistant/ArchiveAssistantPanel.tsx`, `apps/web/src/hooks/useArchiveQa.ts`, `apps/web/src/api/archive.ts` | §3.9 |
| **F3** | `apps/web/src/components/assistant/DocumentCitationGroup.tsx` | F2 |
| **F4** | `apps/web/src/pages/DocumentPage.tsx` (deep-link params only) | §3.9 |
| **F5** | `apps/web/src/components/assistant/ArchiveAssistantStates.tsx` | F2 |
| **F6** | `apps/web/src/components/assistant/ArchiveAssistantPanel.test.tsx` + responsive spec | F2–F5 |
| **G1..G9** | one spec file each under `apps/web/e2e/` or `tests/e2e/` | all above |

---

## 6. Parallel waves

| Wave | Workers launched together | Gate before next wave |
| --- | --- | --- |
| **A** | A1, A2*, A4, A5 in parallel; A3 after A4's type lands; A6 after A1 | `make db-migration-test` on SQLite **and** on PG+pgvector; `pytest tests/integration` green; Claude reviews all five diffs |
| **B** | B1 first (contract), then B2, B3, B4 in parallel; B5 after; B6, B7 after B5 | `pytest tests/unit/test_archive_* services/api/tests/test_archive_*` + PG integration |
| **C** | C2, C3, C4, C5, C6 in parallel; C1 after C2/C3; C7 after C6 | archive retrieval integration test on PG |
| **D** | D3 first; then D1; then D2, D4, D5, D6 in parallel | `pytest services/api/tests/test_archive_qa_api.py` |
| **E** | E1 first; then E2, E8 in parallel; then E3–E7, E9 | `make archive-retrieval-eval` |
| **F** | F1, F2 in parallel (contract-frozen); then F3, F4, F5; F6 last | `npm run test:run` + `npm run build` |
| **G** | G1, G2, G4, G5, G7, G8 in parallel; G3, G6, G9 after | full `make check` |

*A2 drafts against A1's findings; Claude re-reviews the ADR after A1 lands rather than blocking.

---

## 7. Migration strategy

Two new revisions, Alembic only, no runtime `create_all`.

**`0005_phase5_pgvector`** (down_revision `0004_phase4_chunk_index`)

*upgrade, PostgreSQL:*
1. `CREATE EXTENSION IF NOT EXISTS vector` (fails loudly if the role cannot; that failure is
   an actionable message, not a silent skip).
2. `ALTER TABLE document_chunks DROP COLUMN embedding`
3. `ALTER TABLE document_chunks ADD COLUMN embedding vector(1024) NULL`
4. `UPDATE document_chunks SET embedding_version = NULL, embedding_model = NULL`

Step 4 is the safety mechanism, not an afterthought: with `embedding_version` cleared,
`needs_reindex()` (`stats.embedded_chunks < stats.total_chunks`) returns `True` for every
document, so the existing indexing worker re-embeds on the next pass. **No JSON→vector
numeric conversion is attempted.** Chunk text, section paths, page numbers and source block
IDs — all derived-but-expensive data — are preserved; only the vectors are discarded.

*upgrade, SQLite:* no-op. `EmbeddingVector` already resolves to `JSON` there, so the shipped
schema and the model agree and the whole SQLite suite keeps running unchanged.

*downgrade, PostgreSQL:* drop the `vector` column, re-add `embedding JSON NULL`, clear
`embedding_version`/`embedding_model` again. The `vector` extension is **not** dropped —
dropping a shared extension could break unrelated objects in the same database, which matters
on a Supabase project the user already uses.

*Authoritative data touched: none.* `documents`, `parse_runs` (including `canonical`),
`feedback_events` and `jobs` are not read or written by either direction.

**`0006_phase5_document_relations`** (down_revision `0005_phase5_pgvector`) — creates the
table in §3.7 on both dialects (JSON columns, composite FK, CHECK constraint; SQLite gets the
CHECK as a table-level constraint). Downgrade drops the table.

**Tested paths (mandatory, all four):**
1. upgrade from an **empty** PG database → head;
2. upgrade from a populated **Phase 4** PG database (documents + parse_runs + JSON embeddings
   seeded at `0004`, then `upgrade head`) → asserts documents/parse_runs/feedback rows and
   chunk text survive byte-identically, embeddings are `NULL`, and `needs_reindex` is `True`;
3. `downgrade base` from head on PG;
4. full upgrade/downgrade on SQLite.

---

## 8. Supabase integration strategy

**Discovered state — recorded exactly as found, nothing inferred:**

| Probe | Result |
| --- | --- |
| `grep -ril supabase` over the whole tree | no matches |
| `supabase/config.toml` | absent |
| `~/.supabase` | absent |
| `supabase` CLI | **not installed** |
| `SUPABASE_*`, `DATABASE_URL`, `POSTGRES_*` in the environment | **unset** |
| `.env` | absent (only `.env.example`, which points at `localhost:5432`) |
| Project ref | **not discoverable from this machine** |

The task brief states a Supabase project already exists and is linked externally. Nothing in
this repository or this shell can see it, and **no project ref, connection string, or metric
will be invented.** Per the brief's own fallback clause, Phase 5 is therefore built and
verified against **local PostgreSQL 16 + pgvector in Docker**, and every live-Supabase item is
recorded as `NOT_RUN / BLOCKED_BY_CREDENTIALS`.

Strategy, unchanged either way:
- The stack stays **React → FastAPI → SQLAlchemy → PostgreSQL**. No `supabase-py`, no
  PostgREST client, no direct browser→database access. The frontend's only data source
  remains the FastAPI origin, which is verified structurally by A6 (no Supabase URL/anon key
  may appear in `apps/web/**` or any built bundle).
- Alembic stays the single schema authority; a Supabase deployment runs the same
  `alembic upgrade head`. Supabase Auth and Storage remain out of scope.
- `A1` writes `docs/phase-5/supabase-discovery.md` documenting exactly the table above plus
  the precise commands an operator with credentials must run to complete live verification
  (`supabase link --project-ref …`, `supabase db execute "select extname from pg_extension"`,
  `alembic upgrade head` against the pooled connection string, and the anonymous Data API
  probe in A6).
- `A6` ships an **executable** anonymous-exposure probe that is skipped-with-reason when
  `SUPABASE_URL` / `SUPABASE_ANON_KEY` are unset, and fails hard when they are set and any of
  `documents`, `parse_runs`, `document_chunks`, `feedback_events`, `jobs`,
  `document_relations` returns a row. CI never requires the credentials; the gate is
  release-blocking only when they exist.

If the user supplies credentials during this run, A6's probe and a live `alembic upgrade head`
against the pooled connection are executed and reported as real evidence — the plan does not
change, only the recorded result.

---

## 9. E2E cases (the 15 mandatory cases, mapped)

| # | Case | Owner | Where it is proven |
| --- | --- | --- | --- |
| 1 | Newly indexed document immediately retrievable | G1 | upload → parse → index → archive QA in one process; document appears in results |
| 2 | No restart required | G1 | same live FastAPI app object across the whole test |
| 3 | No fine-tuning required | G1 | asserts only `embed_documents` was called; no training entry point exists |
| 4 | Exact document-number query ranks correct doc first | G2 | `19/2026/TT-BGDĐT` → rank 1, against ≥2 near-miss numbers |
| 5 | Metadata-filtered query leaks no outside doc | G4 | every returned `document_id` ∈ filter set, for each filter field |
| 6 | Old + current parse versions; current only retrieved | G5 | v1 and v2 chunks both present in DB; v1 chunk ids never appear |
| 7 | "Newest" query returns newest relevant document | G6 | `issued_date` ordering over a same-topic old/new pair |
| 8 | Newest query does not fabricate supersession | G6 | answer + `relations` contain no supersedes for a pair with no relation row |
| 9 | Explicit amendment relation surfaced with citation | G6 | relation row with block provenance → `relations[]` entry citing a real `citation_id` |
| 10 | Missing relation not invented | G6 | relation-free pair → `relations == []` |
| 11 | Kế hoạch task/owner/deadline stays associated | G7 | both directions, both tasks — see §11 |
| 12 | Multi-document citations open exact doc/page/block | G3 | browser: click each group's citation → correct `/van-ban/:id?trang=&khoi=`, block highlighted |
| 13 | Injection in one document cannot widen scope | G5 | poisoned chunk instructing "search all documents"; result set unchanged |
| 14 | One failed indexing job does not stop others | G1 | three documents, middle one raises; other two reach `READY` and are retrievable |
| 15 | Anonymous Supabase access cannot read private tables | G8/G9 | G8 structural (no anon key/URL in web bundle, no direct-DB client); G9 live probe or `NOT_RUN` |

---

## 10. Eval gates

Deterministic corpus (E1), sanitized/synthetic, born-digital canonical JSON: one Công văn,
**three** Kế hoạch, one Quyết định, one Thông tư, one Nghị định-like fixture, an old/new
same-topic pair, a cross-reference pair, and ≥3 unrelated hard negatives.

Reported per document type **and** per question:
`Recall@{1,3,5,10}`, `MRR`, `nDCG@10`, exact-identifier accuracy, metadata-filter accuracy,
citation correctness, citation completeness, abstention correctness, stale-version leakage,
wrong-document leakage, freshness correctness, relation correctness, task-owner accuracy,
task-deadline accuracy, latency P50/P95.

**Release-blocking thresholds** (asserted in CI, not merely reported):

| Metric | Gate |
| --- | --- |
| stale-version leakage | **exactly 0** |
| wrong-document leakage (filtered queries) | **exactly 0** |
| citation correctness | **1.0** — every citation resolves to a real doc/page/block |
| task-owner accuracy | **1.0** |
| task-deadline accuracy | **1.0** |
| relation correctness (no invented relation) | **1.0** |
| exact-identifier Recall@1 | ≥ 0.90 |
| hybrid+rerank Recall@5 | ≥ lexical-only and ≥ dense-only, on the same corpus |

Baseline comparison (E7) measures **lexical-only / dense-only / hybrid / hybrid+reranker** on
the identical corpus and case file, and the report states the measured deltas. No improvement
is claimed without a number. **No ANN index is added**: exact pgvector search is measured
(E9) and ANN is only reconsidered if measured P95 fails the latency budget.

RAGAS (E8) is supplemental only — faithfulness, answer_relevancy, context_precision,
context_recall — and degrades to the existing typed `UNAVAILABLE` result with no API key. It
gates nothing.

---

## 11. Kế hoạch hard gate

Three Kế hoạch fixtures, each with ≥2 tasks carrying distinct owners and distinct deadlines.
For task A (owner A, deadline A) and task B (owner B, deadline B) in **different documents**
and in the **same** document, both directions are asserted:

```
answer(A).owner    == Owner A     answer(A).owner    != Owner B
answer(A).deadline == Deadline A  answer(A).deadline != Deadline B
answer(B).owner    == Owner B     answer(B).owner    != Owner A
answer(B).deadline == Deadline B  answer(B).deadline != Deadline A
```

Verified through the **full** pipeline — canonical fixture → `build_chunks` → `document_chunks`
in PostgreSQL → pgvector dense + archive BM25 → archive RRF → reranker → multi-document
evidence assembler → `ArchiveQaService` → validated citations — not against an in-memory stub.
The evidence assembler's per-document cap must never merge two documents' task chunks into one
citation; `expand_evidence`'s ancestor-only rule is what keeps a sibling task's owner out.

---

## 12. Security gates

1. **Anonymous private-table read is release-blocking.** A6's probe covers `documents`,
   `parse_runs`, `document_chunks`, `feedback_events`, `jobs`, `document_relations`. Live
   result or an explicit `NOT_RUN / BLOCKED_BY_CREDENTIALS`.
2. **No direct frontend→database path.** Static assertion that `apps/web/**` contains no
   Supabase URL, anon key, or database client, and that every network call goes through
   `apps/web/src/api/client.ts`.
3. **Archive scope cannot be widened by document content.** D6/G5 — injected instructions
   inside an indexed chunk must not change the retrieved document set, the filters, or the
   citation allow-list. The existing `wrap_untrusted_document` delimiters and system policy
   are the primary control; the archive prompt adds an explicit "the evidence set is fixed"
   clause.
4. **Citation allow-list is enforced server-side after generation**, and the router
   independently re-checks that every cited `document_id` is in the retrieved current-version
   set before responding.
5. **FastAPI DB access must not be broken** by any RLS/exposure change: A6 documents the
   configuration but changes no privilege that the API's own role depends on; the API's
   connection uses a role that is not the anon role.
6. `make secret-scan` must stay green; no credential is ever written to a tracked file.

---

## 13. Rollback plan

| Failure | Rollback |
| --- | --- |
| pgvector migration wrong on a live DB | `alembic downgrade 0004_phase4_chunk_index` restores the JSON column; authoritative rows untouched; re-run indexing to repopulate. |
| Extension not permitted by the DB role | `0005` fails loudly at step 1 before any DDL on `document_chunks`; the database is left exactly at `0004`. |
| Archive retrieval regresses single-document QA | The archive path is additive: `QaService`, `DocumentIndex`, `reciprocal_rank_fusion` and `validate_rerank_candidates` keep their existing signatures and guards. Reverting `services/api/app/routers/archive.py` + the archive router registration removes the whole feature without touching Phase 4. |
| A worker's diff is wrong | Not committed. Claude reviews every diff before `git add`; rejected work is sent back with concrete instructions and the tree is restored with `git checkout -- <owned files>`. |
| Whole phase fails the gate | `git reset --hard 0b26b97`. Nothing is pushed to `origin/main` until the full gate in §14 is green. |

Every wave is committed as its own reviewed commit on `main`, so `git revert` of a single wave
is possible without unwinding the phase.

---

## 14. Final gate

```
pytest tests/unit tests/integration services/api/tests   # incl. PG+pgvector
make db-migration-test                                    # SQLite
MAMAGIFT_TEST_DATABASE_URL=postgresql+psycopg://… make db-migration-test
make archive-retrieval-eval        # new target, deterministic, no network
make archive-qa-e2e                # new target
make web-e2e-smoke                 # incl. archive browser E2E
pytest tests/security
# inherited, unchanged:
make parser-contract-tests parser-benchmark-smoke ingestion-integration \
     admin-parser-golden-tests feedback-tests retrieval-eval-tests \
     ai-worker-contract rag-unit-tests rag-eval-mini
make check
git diff --check
```

CI must not require live Supabase, a GPU, the Windows home worker, a live Qwen, or a paid
RAGAS key. The pgvector integration job uses the `pgvector/pgvector:pg16` service container;
every pgvector test is skipped-with-reason when no PostgreSQL URL is configured, and the
SQLite suite keeps running everywhere.

---

## 15. Status contract fix (deliberate)

`docs/PHASE_STATUS.md` currently sets Phase 4 to `COMPLETE_WITH_EXTERNAL_OCR_BLOCKER` while
its own "Status values" list allows only `NOT_STARTED`, `IN_PROGRESS`, `BLOCKED`, `COMPLETE`,
`BLOCKED_BY_PHASE_<N>`. That contradiction is resolved by **separating execution status from
carried limitation**, not by extending the enum:

- a phase's `Status` is drawn from the existing five values only;
- a new, separate `Known blocker:` line carries the limitation and names its ADR/evidence;
- Phase 4 becomes `Status: COMPLETE` + `Known blocker: real scanned-document production
  evidence — ADR-001 PENDING EVIDENCE`;
- Phases 1, 2 and 3 keep `IN_PROGRESS` with the same explicit blocker line;
- `tools/ci/check_docs.py` is extended to **enforce** that every `Status:` value is in the
  allowed set, so this class of drift fails CI rather than accumulating.

ADR-001 remains `PENDING EVIDENCE`. Phase 5 does not solve OCR, and no Phase 5 evidence
claims production readiness for scanned Vietnamese PDFs; every Phase 5 fixture is born-digital
or synthetic and is labelled as such.
