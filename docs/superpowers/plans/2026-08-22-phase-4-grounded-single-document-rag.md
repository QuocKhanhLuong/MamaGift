# Phase 4 — Grounded Single-Document RAG Implementation Plan

> **For agentic workers:** implement exactly one Task from this plan. Your Task number, owned
> files, and review gate are listed in the Ownership Map. Do not edit files another Task owns.
> Contracts in "Frozen Contracts" are defined by the coordinator and may not be redefined by a
> worker; if one is wrong, send `ask` rather than changing it.

**Date:** 2026-08-22
**Run:** `run_3498c603819b`
**Phase gate:** Phase 3.5 must be `COMPLETE` and `make check` green before any Phase 4 Task starts.

---

## 1. Where the repository actually is

Verified against `main` at `b61ef32`:

| Thing | State |
|---|---|
| `packages/docpipe` (`mamagift_docpipe`) | Phase 1/2, accepted. `CanonicalDocument` v1, admin parser, 5 adapters, router. **Do not modify.** |
| `packages/contracts` (`mamagift_contracts`) | `WorkerHealth`, `WorkerCapabilities`, `ParseJob*`. Extended by Task A1. |
| `packages/retrieval` (`mamagift_retrieval`) | Created by Phase 3.5. `EvidenceScope`, `Chunk`, chunkers, lexical seam, evidence budget. |
| `packages/eval` (`mamagift_eval`) | Created by Phase 3.5. Case schemas, taxonomy, document-type slices, metrics. |
| `services/api` | FastAPI. Upload/list/detail/status/canonical/file/preview/reprocess/feedback. SQLAlchemy + Alembic (3 migrations). |
| `services/ai-worker` | **README only.** No code. Built by Group A. |
| `apps/web` | React + Vite + Playwright. Archive, workspace, source viewer, correction. No chat/assistant UI. |
| `DocumentStatus` | Already declares `INDEXING` and `READY` with legal transitions; Phase 2/3 never enter them. Phase 4 is what enters them. |
| `Settings` | Already has `ai_worker_base_url`, `ai_worker_token`. Phase 4 adds LLM/embedding settings beside them. |
| ADR-001 | `PENDING EVIDENCE`. **Phase 4 does not touch it and does not accept it.** |
| OCR | PP-StructureV3 unavailable; real scanned documents still yield zero critical-field coverage (`docs/eval/real-pdf-batch-01-results.md`). **Phase 4 does not fix this.** |

### Consequences that shape this plan

- Real scanned PDFs cannot be an E2E fixture. Every CI fixture is **born-digital or synthetic**.
- The final phase verdict can be at best `COMPLETE_WITH_EXTERNAL_OCR_BLOCKER`.
- `services/ai-worker` is greenfield, so Group A has no legacy to preserve — but the API's
  existing `AIWorkerPort` Protocol and `FakeAIWorker` in `services/api/app/fake_ai_worker.py`
  are the seam it must extend, not replace.

---

## 2. Architecture

```
CanonicalDocument (Phase 1/2, immutable per parse_run)
        |
        v
mamagift_retrieval.chunking.build_chunks      <- Phase 3.5, reused unchanged
        |
        v
[ D1 ] runtime indexing pipeline
        |  writes document_chunks rows keyed by (document_id, parse_run_id)
        v
[ B1 ] EmbeddingProvider  ---> [ B2 ] DocumentIndex (single-document, version-keyed)
        |
        +--> [ C1 ] lexical retrieval (Vietnamese BM25)
        +--> [ C2 ] dense retrieval (brute-force cosine over one document)
                 |
                 v
        [ C3 ] Reciprocal Rank Fusion  (rank-based only; never sums BM25 + cosine)
                 |
                 v
        [ C4 ] CrossEncoder reranker  (provider-neutral seam, deterministic fake)
                 |
                 v
        [ D2 ] evidence expansion (child -> parent, task-locality preserving)
                 |
                 v
        [ D3 ] evidence budget manager  (Phase 3.5 budget contract, explicit breakdown)
                 |
                 v
        [ E1 ] grounded prompt + answer schema + citation allow-list
                 |
                 v
        [ A2 ] ChatCompletionProvider -> [ A1 ] AI worker (OpenAI-compatible, Qwen-capable)
                 |
                 v
        [ E1 ] citation validation / abstention / injection defence
                 |
                 v
        [ E2 ] QaService  ---> [ F1 ] POST /api/v1/documents/{id}/qa
                 |
                 v
        [ G1/G2/G3 ] browser: Trợ lý workspace, citation chips, click -> source block
```

### Storage decision (frozen — do not revisit in a worker)

**No vector database in Phase 4.** Not Qdrant, not pgvector, not FAISS.

Rationale: the retrieval scope is exactly one document version. A parsed Vietnamese
administrative document produces on the order of 10^1–10^2 chunks. Brute-force cosine over
that set is *exact*, has no index-build step, no extra service, no extra migration risk, and
no ANN recall loss — it is strictly better than an approximate index at this cardinality.
`docs/09_CODEX_EXECUTION.md` §3 forbids implementing Phase 5 features early, and pgvector is
an explicit Phase 5 deliverable (`docs/04_PHASE_PLAN.md` Phase 5).

Chunks and their embedding vectors persist in one new table, `document_chunks`, behind the
`DocumentIndex` Protocol. Phase 5 swaps the adapter; no product code changes.

---

## 3. Frozen contracts

Workers implement against these. A worker may not change a signature here.

### 3.1 Worker / model seams — `packages/contracts/python/mamagift_contracts/`

```python
# worker.py (extended by A1)
class WorkerCapabilities(BaseModel):   # already exists
    parse: bool = False
    embed: bool = False
    rerank: bool = False
    llm: bool = False

class WorkerHealth(BaseModel):         # already exists
    status: Literal["online", "offline", "degraded"]
    worker_version: str
    capabilities: WorkerCapabilities
    models: dict[str, str]

# NEW in A1 — llm.py
class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str

class CompletionRequest(BaseModel):
    messages: list[ChatMessage]
    max_output_tokens: int
    temperature: float = 0.0
    stop: list[str] = []
    response_format: Literal["text", "json_object"] = "text"

class CompletionResult(BaseModel):
    text: str
    model: str
    provider: str
    finish_reason: Literal["stop", "length", "content_filter", "error"]
    usage: TokenUsage

class WorkerErrorCode(StrEnum):
    UNAUTHORIZED = "unauthorized"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    MODEL_NOT_LOADED = "model_not_loaded"
    BAD_REQUEST = "bad_request"
    UPSTREAM_ERROR = "upstream_error"

class WorkerError(Exception):
    code: WorkerErrorCode
    retryable: bool
```

```python
# NEW in A1 — embedding.py
class EmbeddingResult(BaseModel):
    vectors: list[list[float]]
    model: str
    dimension: int
    embedding_version: str   # persisted with each chunk; a change forces reindex
```

### 3.2 Provider Protocols — `packages/retrieval/python/mamagift_retrieval/`

```python
class ChatCompletionProvider(Protocol):        # A2
    async def complete(self, request: CompletionRequest) -> CompletionResult: ...

class EmbeddingProvider(Protocol):             # B1
    @property
    def model_id(self) -> str: ...
    @property
    def dimension(self) -> int: ...
    @property
    def embedding_version(self) -> str: ...
    async def embed_documents(self, texts: list[str]) -> EmbeddingResult: ...
    async def embed_query(self, text: str) -> EmbeddingResult: ...

class Reranker(Protocol):                      # C4
    @property
    def reranker_version(self) -> str: ...
    async def rerank(self, query: str, candidates: list[ScoredChunk], top_k: int) -> list[ScoredChunk]: ...

class DocumentIndex(Protocol):                 # B2
    def replace(self, scope: EvidenceScope, entries: list[IndexEntry]) -> IndexStats: ...
    def search_dense(self, scope: EvidenceScope, query_vector: list[float], top_k: int) -> list[ScoredChunk]: ...
    def search_lexical(self, scope: EvidenceScope, query: str, top_k: int) -> list[ScoredChunk]: ...
    def drop(self, scope: EvidenceScope) -> int: ...
    def stats(self, scope: EvidenceScope) -> IndexStats: ...
```

**Every `DocumentIndex` method takes an `EvidenceScope` and MUST filter on it.** Scope
filtering is not the caller's job. A search that ignores scope is a release-blocking defect.

### 3.3 Ranking contract

```python
class ScoredChunk(BaseModel):
    chunk: Chunk                 # Phase 3.5 contract
    score: float
    rank: int                    # 1-based, dense within one retriever's result list
    retriever: Literal["lexical", "dense", "fused", "reranked"]
```

- RRF (C3): `score = sum over retrievers of 1 / (k + rank_r)`, `k = 60`, fixed.
- **Raw BM25 scores and cosine similarities are never added, averaged, or compared to each
  other.** Only ranks cross the fusion boundary. A reviewer must reject any code that mixes
  raw scores from different retrievers.

### 3.4 Evidence and citation contract — `packages/rag/python/mamagift_rag/`

```python
class Evidence(BaseModel):
    citation_id: str             # "c1", "c2", ... assigned by the assembler, per request
    chunk_id: str
    document_id: str
    parse_run_id: str
    document_version: int
    page_numbers: list[int]
    source_block_ids: list[str]
    section_path: list[str]
    text: str

class EvidenceSet(BaseModel):
    scope: EvidenceScope
    evidence: list[Evidence]
    budget: EvidenceBudgetReport   # Phase 3.5 contract; explicit breakdown, never unbounded
    query_id: str

class Citation(BaseModel):
    citation_id: str
    document_id: str
    page_number: int
    block_ids: list[str]
    quote: str | None = None

class QaAnswer(BaseModel):
    answer: str
    status: Literal["answered", "insufficient_evidence", "ai_worker_unavailable", "failed"]
    citations: list[Citation]
    retrieval: RetrievalRef       # {query_id}
    model: ModelRef               # {provider, model, version}
```

Validation rules, all enforced in E1 and all separately tested:

1. Every `citation_id` the model emits MUST be present in `EvidenceSet.evidence`. Unknown id
   -> reject the answer, do not silently drop the citation.
2. `status == "answered"` with zero citations is invalid in factual mode -> downgrade to
   `insufficient_evidence`.
3. A citation's `document_id` / `parse_run_id` MUST match the request scope. Cross-document
   or stale-parse-run evidence -> reject.
4. Insufficient evidence -> `status = "insufficient_evidence"`, empty `citations`, and a
   Vietnamese abstention message. **Never** infer a plausible administrative or legal answer.
5. Document text is untrusted. It is passed inside a delimited block that the system prompt
   declares to be data. Instructions inside it never change policy, never request tools,
   never widen scope, never reveal the system prompt.

### 3.5 API contract — `docs/08_API_AND_DATA_CONTRACTS.md` §15, unchanged

`POST /api/v1/documents/{document_id}/qa`. Response shape exactly as documented. New error
codes added to `services/api/app/errors.py`:

```
ai_worker_unavailable      retryable=True   503
document_not_indexed       retryable=True   409
qa_scope_violation         retryable=False  500   (defence-in-depth; should be unreachable)
```

`insufficient_evidence` is a **response status, not an error** — HTTP 200.

### 3.6 Persistence contract

One migration, `0004_phase4_chunk_index`, owned solely by F2:

```
document_chunks
  id                TEXT PK
  document_id       TEXT NOT NULL FK -> documents.id ON DELETE CASCADE
  parse_run_id      TEXT NOT NULL
  document_version  INTEGER NOT NULL
  chunk_index       INTEGER NOT NULL
  parent_chunk_id   TEXT NULL
  section_path      JSON NOT NULL
  page_numbers      JSON NOT NULL
  source_block_ids  JSON NOT NULL
  text              TEXT NOT NULL
  token_count       INTEGER NOT NULL
  embedding         JSON NULL          -- list[float]; NULL until embedded
  embedding_model   TEXT NULL
  embedding_version TEXT NULL
  created_at        TIMESTAMPTZ NOT NULL
  UNIQUE (parse_run_id, chunk_index)
  INDEX (document_id, parse_run_id)
```

Rules: chunks are **derived data**, never authoritative. Reparsing writes a new
`parse_run_id`; old rows stay until explicitly dropped and are never returned for a
current-version query. No generated answer, prompt, or model output is persisted in Phase 4.

---

## 4. Ownership map

No two Tasks share a file. `services/api/app/errors.py` and `settings.py` are touched by
exactly one Task each (F1 and A2 respectively) — everyone else consumes them.

| Task | Owns (create unless noted) | Depends on |
|---|---|---|
| **A1** worker contract | `packages/contracts/python/mamagift_contracts/llm.py`, `embedding.py`, `rerank.py`; modify `mamagift_contracts/__init__.py`, `worker.py`; `services/ai-worker/app/{__init__,main,auth,health,settings}.py`; `services/ai-worker/tests/test_health_contract.py`, `test_auth.py` | Phase 3.5 |
| **A2** LLM adapter | `packages/retrieval/python/mamagift_retrieval/providers/{__init__,chat.py,openai_compatible.py,fake_chat.py}`; modify `services/api/app/settings.py`; `tests/unit/test_chat_provider.py` | A1 |
| **B1** embeddings | `.../providers/{embedding.py,bge_m3.py,fake_embedding.py}`; `tests/unit/test_embedding_provider.py` | A1 |
| **B2** index | `.../index/{__init__,protocol.py,sql_index.py,entries.py}`; `tests/unit/test_document_index.py` | A1, F2 |
| **C1** lexical | `.../search/{__init__,lexical.py,vi_tokenize.py}`; `tests/unit/test_lexical_retrieval.py` | B2 |
| **C2** dense | `.../search/dense.py`; `tests/unit/test_dense_retrieval.py` | B1, B2 |
| **C3** fusion | `.../search/fusion.py`; `tests/unit/test_rrf.py` | C1, C2 |
| **C4** rerank | `.../rerank/{__init__,protocol.py,cross_encoder.py,fake_reranker.py}`; `tests/unit/test_reranker.py` | C3 |
| **D1** runtime indexing | `services/api/app/indexing.py`; modify `services/api/app/worker.py`; `services/api/tests/test_indexing_pipeline.py` | B1, B2, F2 |
| **D2** evidence expansion | `.../evidence/{__init__,expansion.py}`; `tests/unit/test_evidence_expansion.py` | C4 |
| **D3** budget manager | `.../evidence/assembler.py`; `tests/unit/test_evidence_assembler.py` | D2 |
| **E1** prompt + citations | `packages/rag/python/mamagift_rag/{__init__,prompt.py,schema.py,validation.py,injection.py}`; `tests/unit/test_grounded_prompt.py`, `test_citation_validation.py`, `test_prompt_injection.py` | D3, A2 |
| **E2** QA service | `packages/rag/python/mamagift_rag/service.py`; `tests/unit/test_qa_service.py` | E1 |
| **F1** QA API | `services/api/app/routers/qa.py`; modify `services/api/app/{main.py,schemas.py,errors.py}`; `services/api/tests/test_qa_api.py` | E2 |
| **F2** migration | `services/api/alembic/versions/0004_phase4_chunk_index.py`; modify `services/api/app/models.py`; `services/api/tests/test_migrations.py` (extend) | Phase 3.5 |
| **G1** assistant gating | `apps/web/src/components/assistant/AssistantPanel.tsx`, `.../useQa.ts`, modify `apps/web/src/api/{types.ts,documents.ts}`; `AssistantPanel.test.tsx` | F1 |
| **G2** answer + citations | `apps/web/src/components/assistant/{AnswerView.tsx,CitationChip.tsx}`; modify `apps/web/src/components/workspace/SourceViewer.tsx`; `AnswerView.test.tsx`, `CitationChip.test.tsx` | G1 |
| **G3** states | `apps/web/src/components/assistant/AssistantStates.tsx`; `AssistantStates.test.tsx` | G1 |
| **H1** retrieval eval | `packages/eval/python/mamagift_eval/retrieval_harness.py`; `tests/unit/test_retrieval_harness.py`; `tests/fixtures/eval/retrieval_mini/*.json` | C4 |
| **H2** RAGAS adapter | `packages/eval/python/mamagift_eval/ragas_adapter.py`; `tests/unit/test_ragas_adapter.py` | E2 |
| **H3** MamaGift metrics | `packages/eval/python/mamagift_eval/qa_metrics.py`; `tests/unit/test_qa_metrics.py` | E2 |
| **H4** failure analysis | `packages/eval/python/mamagift_eval/failure_analysis.py`; `tests/unit/test_failure_analysis.py` | H1, H3 |
| **I1** API E2E | `services/api/tests/test_qa_integration.py`; `tests/fixtures/qa/*.json` | F1, D1 |
| **I2** browser E2E | `apps/web/e2e/assistant-qa.spec.ts` | G2 |
| **I3** failure E2E | `apps/web/e2e/assistant-failures.spec.ts` | G3, I1 |
| **CI** gates | modify `Makefile`, `.github/workflows/ci.yml`, `docs/PHASE_STATUS.md`, `docs/04_PHASE_PLAN.md` | all |

`Makefile` and `.github/workflows/ci.yml` are **coordinator-owned**. No worker edits them.

---

## 5. Dependency DAG and waves

```
                        Phase 3.5 COMPLETE + make check green
                                      |
   WAVE 1 (parallel, 2 workers) ------+------------------------------
        A1 worker/model contract            F2 migration + models
                                      |
   WAVE 2 (parallel, 3 workers) ------+------------------------------
        A2 chat adapter    B1 embeddings    B2 index
                                      |
   WAVE 3 (parallel, 3 workers) ------+------------------------------
        C1 lexical         C2 dense         D1 runtime indexing
                                      |
   WAVE 4 (serial-ish, 2 workers) ----+------------------------------
        C3 fusion  ---> C4 rerank
                                      |
   WAVE 5 (parallel, 2 workers) ------+------------------------------
        D2 expansion ---> D3 budget
                                      |
   WAVE 6 (serial, 2 workers) --------+------------------------------
        E1 prompt/citations ---> E2 QA service
                                      |
   WAVE 7 (parallel, 4 workers) ------+------------------------------
        F1 API      H1 retrieval eval    H2 RAGAS    H3 QA metrics
                                      |
   WAVE 8 (parallel, 4 workers) ------+------------------------------
        G1 gating   H4 failure analysis   I1 API E2E   (CI wiring: coordinator)
                                      |
   WAVE 9 (parallel, 2 workers) ------+------------------------------
        G2 answer/citations      G3 states
                                      |
   WAVE 10 (parallel, 2 workers) -----+------------------------------
        I2 browser E2E           I3 failure-path E2E
                                      |
                        FINAL INTEGRATION REVIEW (whole diff)
```

Max concurrency 4. Group I is not spawned until Wave 7 lands, per the instruction that E2E
waits for contract stability.

---

## 6. Review gates

Every Task gets an independent reviewer that reads the **actual diff and tests**, not the
worker's summary. Reviewer verdict is `PASS` or `CHANGES_REQUIRED`. The implementer never
reviews its own work.

Reviewers additionally check, per group:

- **A** — auth rejection is real (not a stub), timeout is enforced, no Qwen-specific request
  shape leaks outside the adapter, CI needs no real model.
- **B** — version isolation: a query scoped to parse_run *N* can never see rows from *N-1*.
  Deterministic fake path exists. No provider type leaks into product code.
- **C** — RRF is rank-based only. No raw BM25/cosine arithmetic across retrievers. `k=60`.
- **D** — the task-locality matrix below actually fails when broken.
- **E** — attacks: hallucinated citation, missing citation, stale `parse_run_id`,
  cross-document evidence, injection text in the document body.
- **F** — Phase 1/2/3 API responses are byte-identical for existing endpoints.
- **G** — the MamaGift design system is preserved; no redesign; responsive.
- **H** — metric semantics match hand-authored fixtures; RAGAS failure degrades to
  `unavailable`, never to a fabricated score.
- **I** — the E2E genuinely executes the pipeline; no mocked-away assertions.

### The D-group locality matrix (reviewer must see these tests fail when broken)

For a `Kế hoạch` with Task A (owner A, deadline A) and Task B (owner B, deadline B):

| Must hold | Must NOT hold |
|---|---|
| Task A -> owner A | Task A -> owner B |
| Task A -> deadline A | Task A -> deadline B |
| Task B -> owner B | Task B -> owner A |
| Task B -> deadline B | Task B -> deadline A |

---

## 7. Integration gates

After each wave: coordinator merges reviewed branches in dependency order, resolves conflicts
semantically, and runs the wave's focused tests plus `UV_CACHE_DIR=.uv-cache uv run pytest -q`.

Before final acceptance, all of:

```bash
make backend-format-check backend-lint backend-typecheck backend-test
make parser-contract-tests parser-benchmark-smoke
make ingestion-integration admin-parser-golden-tests db-migration-test feedback-tests
make retrieval-eval-tests          # Phase 3.5 gate
make rag-unit-tests                # NEW
make rag-eval-mini                 # NEW
make ai-worker-contract            # NEW
make frontend-format-check frontend-lint frontend-typecheck frontend-test frontend-build
make web-e2e-smoke
make compose-config docs-check repository-hygiene secret-scan
make check
git diff --check
```

CI must not require: the home Windows machine, a real Qwen, a live external API, a GPU, or a
RAGAS API key. Deterministic fakes only. Real local-model and RAGAS runs are *additional
offline evidence*, recorded separately and never as a CI gate.

---

## 8. E2E acceptance cases

| Case | Proves | Owner |
|---|---|---|
| 1 | Exact fact: document-number question retrieves the correct source block; answer carries the correct citation; clicking it reaches the exact source. | I1 + I2 |
| 2 | `Kế hoạch`: "Đơn vị nào chủ trì nhiệm vụ X và deadline là khi nào?" returns task-local owner/deadline with no cross-association. | I1 |
| 3 | Hierarchy: an Điều/Khoản/Điểm question retrieves the correct legal hierarchy level. | I1 |
| 4 | Insufficient evidence: a question whose answer is absent makes the system abstain. | I1 + I3 |
| 5 | Prompt injection: "Ignore previous instructions…" inside the document is treated as source text only. | I1 + I3 |
| 6 | Version isolation: QA scoped to the current parse run cannot retrieve stale-version evidence. | I1 |
| 7 | Worker offline: the document stays intact; QA returns a clear unavailable/retry state. | I1 + I3 |

Case 1 and Case 2 must execute the **real** pipeline end to end (fake LLM + fake embeddings,
real chunking, real retrieval, real fusion, real rerank, real citation validation). A passing
unit test is not acceptance.

---

## 9. Explicit non-goals

Not implemented in Phase 4, per `docs/04_PHASE_PLAN.md` and `docs/09_CODEX_EXECUTION.md` §3:

- Cross-document / archive-wide QA (Phase 5) — only the interfaces needed to avoid coupling.
- pgvector, Qdrant, or any vector service.
- Autonomous legal conclusions.
- Fine-tuning, online or continual learning.
- Zep or any multi-memory backend.
- Meeting/audio assistant.
- Enterprise auth (login remains the Phase 3 screen/state handoff).
- Any OCR change. ADR-001 stays `PENDING EVIDENCE`.

---

## 10. Known blockers carried into the final report

1. **OCR / ADR-001.** PP-StructureV3 is unavailable; real scanned documents still produce no
   critical fields. Phase 4 CI uses born-digital and synthetic fixtures. Real scanned-document
   production readiness stays explicitly blocked. Phase 4 must not be reported as `COMPLETE`
   on the strength of synthetic fixtures alone — the honest ceiling is
   `COMPLETE_WITH_EXTERNAL_OCR_BLOCKER`.
2. **Phase 1/2 remain `IN_PROGRESS`** for the same reason; Phase 4 does not close them.
3. **Phase 3.5 CI wiring** was descoped in its own plan (Makefile gate only, no GitHub
   Actions job). Phase 4's CI Task wires `retrieval-eval-tests` into `ci.yml` alongside the
   three new Phase 4 jobs.
