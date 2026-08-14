# MamaGift

MamaGift is a small-family AI administrative assistant focused first on Vietnamese administrative PDF documents and later on meeting assistance.

The first product goal is deliberately narrow:

> Upload a Vietnamese administrative PDF, parse it reliably, preserve its structure, and make it queryable with grounded answers and citations.

The project is designed for 3–4 family users. It optimizes for correctness, simplicity, low recurring cost, and evolvability rather than multi-tenant scale.

## Current scope

### In scope now

- Vietnamese administrative/legal PDF ingestion.
- Born-digital vs scanned-PDF routing.
- Parser/OCR benchmarking before locking a foundation.
- Canonical structured-document representation.
- Vietnamese administrative structure extraction: issuer, document number, issue date, title, signer, sections, articles, clauses, points, tables, deadlines, obligations.
- Document viewer and searchable archive.
- Grounded Q&A over one document, then across the document collection.
- Self-hosted LLM inference on a Windows home machine.
- Lightweight public-facing VM for web/API/storage/orchestration.
- OCR feedback capture and later offline continual domain adaptation.

### Explicitly deferred

- Meeting recording/transcription/diarization.
- Native mobile apps.
- Multi-tenant SaaS concerns.
- Kubernetes or distributed infrastructure.
- Training a foundation OCR or LLM from scratch.

## Architecture principle

Use strong existing document-understanding systems as foundations. Specialize the product around Vietnamese administrative structure, reliable retrieval, citations, feedback, and continual improvement.

The initial parser benchmark must compare at least:

- MinerU
- Marker
- Docling
- PaddleOCR / PP-StructureV3
- PyMuPDF as a baseline only

No parser is considered the production default until it wins on the project benchmark corpus.

## Design direction

MamaGift uses a **Claude-inspired interaction model** for chat and a **Granola-inspired warm/editorial visual language**, while remaining document-first and provenance-first. The binding frontend design contract is [`docs/10_DESIGN_SYSTEM.md`](docs/10_DESIGN_SYSTEM.md).

## Documentation

Read in this order:

1. [`docs/00_PROJECT_CHARTER.md`](docs/00_PROJECT_CHARTER.md)
2. [`docs/01_ARCHITECTURE.md`](docs/01_ARCHITECTURE.md)
3. [`docs/02_INFRASTRUCTURE.md`](docs/02_INFRASTRUCTURE.md)
4. [`docs/03_DOCUMENT_PIPELINE.md`](docs/03_DOCUMENT_PIPELINE.md)
5. [`docs/04_PHASE_PLAN.md`](docs/04_PHASE_PLAN.md)
6. [`docs/05_TEST_STRATEGY.md`](docs/05_TEST_STRATEGY.md)
7. [`docs/06_CICD.md`](docs/06_CICD.md)
8. [`docs/07_DATA_AND_CONTINUAL_LEARNING.md`](docs/07_DATA_AND_CONTINUAL_LEARNING.md)
9. [`docs/08_API_AND_DATA_CONTRACTS.md`](docs/08_API_AND_DATA_CONTRACTS.md)
10. [`docs/09_CODEX_EXECUTION.md`](docs/09_CODEX_EXECUTION.md)
11. [`docs/10_DESIGN_SYSTEM.md`](docs/10_DESIGN_SYSTEM.md)

## Phase rule

Every implementation phase has exactly one `/goal`, explicit non-goals, acceptance criteria, required tests, and a CI gate. Codex must not silently pull work from later phases into the current phase.

## Development status

Planning baseline only. Implementation should begin at **Phase 0** in `docs/04_PHASE_PLAN.md`.
