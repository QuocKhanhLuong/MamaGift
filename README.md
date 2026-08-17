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

## Development foundation

The Phase 0 repository foundation is documented in [`docs/SETUP.md`](docs/SETUP.md). It provides locked Python/JavaScript dependencies, a React/Vite health screen, a FastAPI health endpoint, PostgreSQL migrations, Docker Compose, and a deterministic fake AI-worker contract. Document intelligence remains unimplemented until its later phases.

## Development status

Phase 0 foundation complete.

Phase 1 is **in progress**. The parser benchmark harness is complete and tested: a
provider-neutral `DocumentParser` interface, adapters for all five candidates, a PDF
inspection/router, `CanonicalDocument` v1 normalization, and a benchmark CLI that
measures reading order, heading hierarchy, list preservation, table structure,
header/footer leakage, provenance and critical fields alongside CER.

The parser decision itself is **not made**. `docs/decisions/ADR-001-parser-selection.md`
is committed with status `PENDING EVIDENCE` because the required corpus of 30+ real
Vietnamese administrative documents is private and cannot live in this repository. See
[`benchmarks/parser/README.md`](benchmarks/parser/README.md) for how to run the
benchmark against a private corpus.

Phase 2 remains blocked until ADR-001 is decided.
