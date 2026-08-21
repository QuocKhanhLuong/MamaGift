# Implementation Phase Plan

This file is the execution source of truth for Codex.

## Global phase rules

1. Work on one phase at a time.
2. Each phase has one `/goal`; treat it as the optimization target.
3. Do not implement later-phase features unless required to satisfy the current phase contract.
4. Every phase must end with green required tests and updated docs.
5. When a technical choice is unresolved, create an adapter/interface and benchmark rather than hard-coding an assumption.
6. Never add paid external API dependencies as a hidden requirement.
7. Never commit real private family documents to the public repository.

---

# Phase 0 — Repository and deterministic development foundation

## /goal

**Make MamaGift reproducibly buildable and testable on a fresh machine before implementing document intelligence.**

## Deliverables

Recommended repository structure:

```text
apps/
  web/
services/
  api/
  ai-worker/
packages/
  contracts/           # optional if shared generated types are useful
  test-fixtures/       # sanitized/synthetic only
tools/
  parser_bench/
docs/
benchmarks/
  parser/
infra/
  compose/
.github/
  workflows/
```

Expected baseline stack unless implementation discovers a strong reason to adjust:

- Web: React + TypeScript + Vite or Next.js; choose one and document ADR.
- API: Python 3.11+ + FastAPI + Pydantic.
- DB: PostgreSQL.
- Python package management: choose one lockfile-based workflow (uv preferred if no conflict).
- JS package management: npm/pnpm with committed lockfile.
- Docker Compose for integration environment.

Create:

- `.env.example`;
- Python and JS formatting/lint configs;
- `/health` API endpoint;
- minimal web health page;
- DB migration framework;
- test directories;
- local fake AI worker interface;
- base CI workflow.

## Non-goals

- Real OCR/parsing.
- Real LLM inference.
- RAG.
- Production deployment.

## Required tests

- API unit smoke test for `/health`.
- Web unit/render smoke test.
- DB migration applies from empty database.
- Compose config validates.
- fake AI worker contract test.
- lint/typecheck/format-check for Python and TypeScript.

## CI gate

PR cannot merge unless:

```text
docs-check
backend-lint
backend-test
frontend-lint-typecheck-test
compose-config
```

all pass.

## Exit criteria

A new developer/Codex environment can clone the repo and run documented setup/test commands without undocumented machine state.

---

# Phase 1 — PDF parser benchmark and parser decision

## /goal

**Choose the document parsing foundation using evidence from Vietnamese administrative/legal PDF fixtures, not assumptions.**

## Deliverables

Implement:

- PDF inspection/router signals;
- `DocumentParser` interface;
- adapters or benchmark wrappers for:
  - PyMuPDF baseline;
  - MinerU;
  - Marker;
  - Docling;
  - PaddleOCR/PP-StructureV3;
- `CanonicalDocument` v1 normalizer;
- benchmark manifest format;
- benchmark CLI;
- metrics/report generator;
- sanitized/synthetic fixture corpus;
- documentation for running full benchmark outside CI.

Full real-document evaluation may be executed locally/Kaggle/home machine and its summary metrics can be committed without raw private PDFs.

Create a parser decision record at the end of the phase:

```text
docs/decisions/ADR-001-parser-selection.md
```

It must identify primary born-digital route, scan route, fallback strategy, and measured tradeoffs.

## Non-goals

- User-facing Q&A.
- Vector database.
- Full administrative semantic extraction.
- Parser fine-tuning.

## Required tests

### Router unit tests

Fixtures for:

- good text layer;
- empty scan;
- suspicious/garbled text layer;
- mixed PDF;
- rotated page;
- encrypted/unsupported input.

Assert label and diagnostic signals.

### Contract tests

For every adapter:

- stable adapter metadata;
- parse result can normalize to `CanonicalDocument`;
- page provenance survives;
- error mapping follows common error schema.

Heavy adapters may use recorded provider outputs in CI; at least one lightweight end-to-end parser path must run in CI.

### Canonical schema tests

- schema validation;
- deterministic block IDs for one parser run;
- reading-order indexes unique per page;
- bbox validation;
- Unicode normalization does not strip Vietnamese diacritics;
- unsupported/missing fields remain null/unavailable.

### Benchmark harness tests

- manifest validation;
- metric calculation on known toy cases;
- report generation;
- failed parser does not abort other candidate runs;
- repeated run metadata captures versions/config.

## CI gate

Add:

```text
parser-contract-tests
parser-benchmark-smoke
```

Full GPU/heavy benchmark is not required on every PR.

## Exit criteria

- ADR-001 is committed.
- At least 30 representative real PDFs have been evaluated outside the public repo or equivalent benchmark evidence exists.
- Winning parser strategy satisfies hard provenance/reading-order requirements.
- No product code imports a provider directly outside adapters.

---

# Phase 2 — Production ingestion and Vietnamese administrative structure

## /goal

**Turn an uploaded PDF into a versioned, reviewable `CanonicalDocument` with trustworthy Vietnamese administrative structure and critical-field provenance.**

## Deliverables

Implement API/data path:

```text
upload
-> immutable file storage
-> document row
-> inspect
-> parse job
-> normalize
-> Vietnamese admin parser
-> quality report
-> READY_FOR_REVIEW
```

Implement:

- document/job database tables;
- storage abstraction;
- immutable original upload;
- parse-run versioning;
- retry/idempotency behavior;
- selected parser strategy from ADR-001;
- Vietnamese administrative hierarchy parser;
- critical field extraction:
  - document type;
  - document number;
  - issuer;
  - issue date;
  - title/subject;
  - signer where detectable;
  - explicit deadlines when high confidence;
- per-field provenance;
- quality/confidence flags;
- API endpoints for upload/status/document retrieval;
- synthetic/sanitized admin fixtures.

## Non-goals

- Chat/Q&A.
- Cross-document retrieval.
- Continual model training.
- Meeting features.

## Required tests

### Upload/API

- PDF MIME/extension validation;
- duplicate byte upload behavior is defined and tested;
- max-size rejection;
- malformed PDF rejection;
- original bytes checksum persists;
- upload is durable before async processing starts.

### State machine

Test every legal transition and reject illegal transitions.

Test:

- worker unavailable -> job remains retryable;
- lease expiry -> requeue;
- parser error -> recorded failure;
- retry does not create duplicate canonical current version;
- reprocess creates a new parse run rather than overwriting old output.

### Administrative parser

Golden fixtures must cover:

- `Số:` extraction;
- date expressions;
- `Chương/Mục/Điều/Khoản/Điểm` hierarchy;
- numbered/bulleted lists;
- `Nơi nhận`;
- title blocks;
- common signer layout;
- tables/appendices represented without ordering corruption.

### Critical fields

Test exact normalized values and source block/page IDs.

### Integration

One sanitized PDF must execute:

```text
POST upload -> processing -> GET document canonical result
```

using the CI-safe parser path.

## CI gate

Add:

```text
ingestion-integration
admin-parser-golden-tests
db-migration-test
```

## Exit criteria

A representative PDF can be uploaded and inspected through APIs with deterministic canonical output and provenance. Critical fields that cannot be trusted are marked for review.

---

# Phase 3 — Document archive and verification-first web UX

## /goal

**Let a non-technical family user upload, find, inspect, and verify parsed documents without using developer tools.**

## Deliverables

Web flows:

1. login;
2. document list;
3. upload;
4. processing status;
5. document detail;
6. side-by-side original PDF and parsed structure;
7. metadata panel;
8. source-page/block highlighting;
9. correction UI for supported critical fields;
10. search/filter by document metadata.

UX principles:

- Vietnamese-first labels;
- large, simple actions;
- processing state understandable without technical terminology;
- source verification one click away;
- low-confidence fields visibly distinct;
- no prompt engineering required for core workflows.

## Non-goals

- Chat/Q&A.
- Full mobile-native app.
- Complex admin settings.

## Required tests

### Component tests

- upload control;
- processing states;
- metadata rendering;
- low-confidence state;
- correction interaction;
- citation/source jump component.

### API integration tests

- upload happy path;
- failed processing UI;
- retry path;
- document search/filter;
- correction persistence.

### Browser E2E

With Playwright or equivalent:

```text
login -> upload fixture -> wait/mock processing -> open document -> verify metadata -> jump to cited page -> correct field -> reload -> correction persists
```

### Accessibility/basic usability

- keyboard-accessible main controls;
- labelled form fields/buttons;
- no critical status conveyed only by color;
- responsive viewport smoke tests.

## CI gate

Add:

```text
web-component-tests
web-e2e-smoke
```

## Exit criteria

The mother/family-user workflow can be demonstrated entirely from the browser with no terminal involvement.

---

# Phase 3.5 — Evaluation + Retrieval Foundation

## /goal

**Build deterministic evaluation, evidence-scoping, and structure-aware retrieval
foundations before implementing LLM/RAG.**

## Deliverables

- Provider-neutral retrieval/evidence scope contract (`family_id`, `user_id`,
  `thread_id`, `document_id`, `document_version`/`parse_run_id`, archive scope) with
  a fixed authority order: verified current `DocumentVersion` > archive/document
  evidence > user/episodic memory. No memory backend is integrated; a verified
  document fact is never silently overridden.
- A structure-aware `Chunk` contract derived only from `CanonicalDocument`, with
  parent/child links and full block/page provenance. Nothing is embedded or indexed.
- Deterministic hierarchical chunkers: one over the existing legal
  `Chương/Mục/Điều/Khoản/Điểm/Phụ lục` hierarchy, one for `Kế hoạch` plan structure
  (`major section -> subsection/task -> child content`) that keeps each task's
  owner/coordinating-unit/deadline scoped to that task alone, and a deterministic
  one-block-per-chunk fallback for unstructured paragraphs — never fixed-token
  windowing when canonical hierarchy exists.
- `Kế hoạch` evaluation fixtures with nested sections, multiple tasks, distinct
  owners/coordinating units/deadlines per task, verified not to cross-associate.
- Deterministic evaluation schemas (`ParserSemanticCase`, `RetrievalQACase`), a
  failure-analysis taxonomy (parser/chunking/retrieval/metadata-version vs.
  generation/grounding), and per-document-type metric hooks — including
  plan-specific task recall/order/owner/deadline accuracy, nested-hierarchy F1, and
  table/appendix preservation.
- Document-type slices (`cong_van`, `quyet_dinh`, `ke_hoach`, `thong_tu`,
  `nghi_dinh`, `table_appendix`, `scanned`) so evaluation reporting is never a
  single aggregate score.
- A naive lexical (token-overlap) retrieval baseline seam and interface, so a later
  hybrid/reranked implementation has a deterministic floor to beat.
- A context/evidence budget contract (selected-document, conversation short-term,
  user long-term memory, episodic memory, archive semantic evidence) with a debug
  breakdown of what was offered vs. used. No production memory implementation.

## Non-goals

- Zep or any other memory backend; long-term/episodic memory implementation.
- Embeddings, a vector store (Qdrant or otherwise), a reranker/CrossEncoder, Qwen,
  or RAGAS.
- BM25/dense/RRF hybrid retrieval beyond the minimal deterministic lexical seam.
- Any LLM evaluator or generation step.
- Starting Phase 4, or accepting ADR-001.
- Resolving the PP-StructureV3/OCR blocker (`docs/eval/real-pdf-batch-01-results.md`)
  — that remains a Phase 1/2 exit criterion, unaffected by this phase.

## Required tests

- Chunk IDs are deterministic across repeated builds of the same document.
- Parent-child chunk links are valid; a dangling or cross-document/version parent
  reference is rejected.
- Source block/page provenance and document-version metadata survive chunking.
- Plan task-owner-deadline relationships survive chunking, and two tasks with
  different owners/deadlines never cross-associate.
- Scope filters (`scope_matches`) cannot leak another document/version/family into
  a retrieval result.
- Unstructured fallback chunking is deterministic and never re-chunks a block the
  legal/plan builders already claimed.
- Eval schema validation (`ParserSemanticCase`, `RetrievalQACase`) rejects unknown
  fields and missing required data.
- Evidence-budget truncation never concatenates categories together and always
  reports a debug breakdown.
- Existing Phase 1/2/3 parser/ingestion/frontend tests remain green.

## CI gate

Add:

# Phase 4 — Self-hosted LLM and grounded single-document Q&A

## /goal

**Answer questions about one selected document using the home-hosted LLM, with every factual answer grounded in retrievable source blocks.**

## Deliverables

### Windows AI node

- worker installation instructions;
- service/auto-start strategy;
- `/health` heartbeat;
- authenticated VM-to-worker calls;
- OpenAI-compatible local LLM endpoint;
- configurable model name/base URL;
- fake provider for tests.

### Retrieval

- hierarchy-aware chunk builder;
- source block IDs retained in chunks;
- embeddings provider interface;
- single-document index;
- retrieval endpoint/service;
- optional lexical fallback/hybrid search if benchmark justifies it.

### Generation

- grounded prompt contract;
- citation ID allow-list;
- insufficient-evidence response;
- answer schema;
- source rendering/jump in UI;
- buttons such as:
  - Tóm tắt;
  - Tôi cần làm gì?;
  - Có deadline nào?;
  - Đối tượng áp dụng?;

## Non-goals

- Search across the entire archive.
- Autonomous legal conclusions.
- Fine-tuning Qwen.

## Required tests

### Worker tests

- online/offline heartbeat;
- auth rejection;
- timeout;
- retry-safe request;
- OpenAI-compatible response adapter.

### Retrieval tests

Curated questions with expected answer-bearing blocks:

- Recall@k;
- exact document isolation;
- heading/context preservation;
- table-derived answer retrieval where supported;
- exact document-number query.

### Generation contract tests

Use fake deterministic LLM responses to test:

- citation IDs validated against retrieved context;
- unknown citation rejected;
- answer cannot omit provenance in factual mode;
- insufficient evidence path;
- prompt-injection text inside the PDF cannot change system policy or request secrets/actions.

### Evaluation set

Create a local/private QA set over real documents and a public sanitized mini-set. Track:

- retrieval recall;
- answer correctness by human rating;
- citation correctness;
- abstention correctness;
- latency.

## CI gate

Add:

```text
rag-unit-tests
rag-eval-mini
ai-worker-contract
```

CI uses fake/lightweight inference and never requires the home Windows machine.

## Exit criteria

A selected document can answer practical questions with verifiable page/block citations. Home-node downtime is represented cleanly and does not corrupt the document.

---

# Phase 5 — Cross-document institutional memory

## /goal

**Answer archive-level questions across newly ingested documents without relying on the LLM training cutoff.**

## Deliverables

- PostgreSQL pgvector migration or selected vector storage;
- incremental indexing on document readiness;
- lexical + vector candidate retrieval;
- metadata filters;
- reranking provider interface;
- document date/type/issuer filtering;
- explicit document-reference relationships;
- explicit supersedes/amends/replaces relationships only when supported by source evidence;
- archive-level chat/search UI;
- freshness-aware query behavior.

Examples to support:

- “Trong các văn bản tháng này có deadline nào?”
- “Văn bản mới nhất liên quan tới tuyển sinh là văn bản nào?”
- “Những việc hiệu trưởng cần làm trong tuần này theo các công văn đã tải lên?”

## Non-goals

- Assume that newer automatically means legally controlling.
- Web search of external laws unless separately designed.
- LLM weight updates for new documents.

## Required tests

- newly ingested document becomes retrievable without retraining;
- metadata filters;
- date ordering;
- exact document-number lookup;
- hybrid retrieval improves/does not regress curated set;
- stale/superseded relation only used if explicitly represented;
- citation spans point to correct document and page;
- deletion/reindex consistency if deletion is supported.

## CI gate

Add:

```text
cross-document-retrieval
incremental-indexing
```

## Exit criteria

Adding a new PDF makes its knowledge queryable after indexing, with no LLM fine-tuning or service restart.

---

# Phase 6 — Feedback dataset and offline continual OCR/domain adaptation

## /goal

**Convert verified user corrections into a versioned training/evaluation dataset and safely improve OCR/parser performance offline without catastrophic regressions.**

## Deliverables

Capture feedback events with:

- raw prediction;
- corrected value/text;
- source image crop reference where available;
- parser/model version;
- confidence;
- correction type;
- timestamp.

Build export tooling for a private training dataset.

Offline training workflow:

```text
production corrections
-> reviewed dataset
-> train/validation split
-> frozen regression benchmark
-> Kaggle/local fine-tune
-> candidate checkpoint
-> benchmark candidate vs production
-> promote or reject
```

Use PaddleOCR fine-tuning or another selected OCR component only if the Phase 1/production failure analysis shows recognition is a bottleneck.

Add model registry metadata:

```text
model_version
base_model
training_dataset_version
training_config
benchmark_results
artifact_checksum
promotion_status
```

## Non-goals

- train after every document;
- online weight updates;
- auto-promote a model because training loss improved;
- retrain the LLM to memorize uploaded documents.

## Required tests

- feedback event append-only behavior;
- corrected view does not destroy raw output;
- dataset export reproducible;
- train/test document leakage detector;
- benchmark comparison script;
- promotion blocked if critical-field regression exceeds threshold;
- rollback to previous model version.

## Promotion gates

A candidate model may deploy only if:

- critical-field accuracy does not regress beyond configured tolerance;
- frozen benchmark passes;
- no catastrophic new failure category appears;
- artifact/version metadata is complete.

## CI gate

CI validates dataset tooling and benchmark logic on synthetic samples. GPU training itself runs manually/Kaggle, not on every GitHub PR.

## Exit criteria

There is a reproducible path from user correction to candidate model to benchmarked deployment, with rollback.

---

# Phase 7 — Production hardening and low-cost deployment

## /goal

**Run the document assistant reliably for daily family use with backups, recovery, monitoring, and controlled releases.**

## Deliverables

- production Docker images;
- VM Compose deployment;
- reverse proxy + HTTPS;
- private home-node tunnel;
- restart policies;
- Windows worker auto-start;
- DB backup job;
- object/file backup plan;
- restore script/runbook;
- structured logs;
- health/status page;
- GitHub Actions build/publish pipeline;
- versioned release/deploy workflow;
- rollback instructions.

## Non-goals

- Kubernetes;
- autoscaling fleet;
- enterprise monitoring suite.

## Required tests

### Deployment smoke

- fresh VM/clean environment starts from documented configuration;
- DB migrations execute;
- upload/read existing document works;
- worker online/offline transition works.

### Failure drills

- API restart during queued job;
- Windows worker disappears mid-job;
- database restore from backup;
- object storage restore/checksum;
- rollback application image;
- disk-full warning behavior where feasible.

### Security smoke

- unauthenticated API endpoints rejected except health where intentionally public;
- worker token required;
- secrets absent from built frontend/log fixtures;
- dependency/security scanning configured with sensible severity policy.

## CI/CD gate

`main` may build immutable container artifacts only after all CI checks pass. Production deployment may initially require manual approval.

## Exit criteria

The family can use MamaGift daily and a documented recovery path exists for VM restart, worker downtime, bad release, and data restoration.

---

# Phase 8 — Meeting assistant (parked future phase)

## /goal

**Add meeting audio as a second ingestion source only after the document product is stable and useful.**

This phase is intentionally parked. Do not implement it during Phases 0–7.

Expected future subproblems:

- browser/native audio capture reliability;
- noisy room recording strategy;
- raw audio retention;
- speech enhancement/VAD;
- Vietnamese ASR;
- diarization if useful;
- meeting summary/action extraction;
- transcript provenance/timestamps;
- ingestion into the same knowledge layer.

Before starting Phase 8, create a separate architecture/test plan based on real meeting recordings and hardware constraints.

---

# Release milestones

## R0 — Parser evidence

End of Phase 1. We know which foundation parser route is justified.

## R1 — Trustworthy document reader

End of Phase 3. User can upload and verify structured PDFs.

## R2 — Useful personal document copilot

End of Phase 4. Single-document grounded Q&A works.

## R3 — Institutional memory

End of Phase 5. Archive-level RAG handles newly added documents.

## R4 — Self-improving document pipeline

End of Phase 6. Verified corrections can improve OCR/parser offline.

## R5 — Daily-use deployment

End of Phase 7. Production is backed up, recoverable, and operationally boring.
