# Architecture

## 1. System context

MamaGift is split into a small always-online control plane and a replaceable heavy-inference plane.

```text
Family browser / PWA
        |
        v
+---------------------------+
| Public VM                 |
|---------------------------|
| Web app                   |
| FastAPI                   |
| PostgreSQL                |
| Object/file storage       |
| Job orchestration         |
| Retrieval orchestration   |
| Auth for 3-4 family users |
+-------------+-------------+
              |
       private authenticated link
              |
              v
+---------------------------+
| Windows Home AI Node      |
|---------------------------|
| Parser adapters           |
| OCR / PP-Structure        |
| Embedding                 |
| Reranker                  |
| Local LLM server          |
| Future: ASR               |
+---------------------------+
```

The VM must remain useful even while the home node is offline: uploads, browsing already-processed documents, job state, and previously indexed search data remain available.

## 2. Architectural boundaries

### 2.1 Web client

Responsibilities:

- upload PDFs;
- show job state;
- browse/search documents;
- side-by-side original/parsed viewer;
- render citations and jump to source page/block;
- collect user corrections;
- provide Q&A UI.

Must not:

- parse documents in-browser;
- contain parser-specific logic;
- depend directly on Ollama/vLLM/Qwen APIs.

### 2.2 API/control plane

Responsibilities:

- authenticate users;
- persist document and job metadata;
- allocate immutable document IDs;
- store originals and normalized parser outputs;
- expose stable REST contracts;
- orchestrate processing jobs;
- call inference adapters;
- implement retrieval policy;
- store feedback/corrections.

### 2.3 Document processing plane

Responsibilities:

- inspect PDFs;
- classify document processing route;
- execute parser/OCR adapters;
- normalize all provider outputs into the canonical document schema;
- compute quality/confidence signals;
- extract Vietnamese administrative structure;
- emit deterministic processing artifacts.

### 2.4 AI inference plane

Responsibilities:

- embeddings;
- reranking;
- LLM inference through an OpenAI-compatible API;
- optional VLM verification for difficult image regions later.

The backend talks to interfaces, never to a model brand directly.

## 3. Logical data flow

```text
UPLOAD
  |
  v
immutable original PDF
  |
  v
PDF inspection
  |
  +--> route: born_digital
  |        |
  |        v
  |    document parser candidate
  |
  +--> route: scanned_or_corrupt_text
           |
           v
       OCR/layout candidate
  |
  v
provider-specific output
  |
  v
CanonicalDocument normalization
  |
  v
Vietnamese administrative parser
  |
  +--> metadata
  +--> hierarchy
  +--> tables
  +--> critical fields
  +--> quality signals
  |
  v
persist versioned parse artifact
  |
  +--> document viewer
  |
  +--> indexing/chunking
          |
          v
      retrieval
          |
          v
       local LLM
          |
          v
 grounded answer + citations
```

## 4. Canonical document model

All parser adapters must output the same conceptual structure. Exact field contracts are in `08_API_AND_DATA_CONTRACTS.md`.

```text
CanonicalDocument
  document_id
  source_file
  parser_run
  metadata
  pages[]
    page_number
    width/height
    blocks[]
      block_id
      type
      text
      bbox
      confidence
      reading_order
      parent_id
      provenance
  hierarchy[]
  tables[]
  extracted_fields[]
  quality_report
```

Critical design rule: the normalized representation keeps both **logical structure** and **physical provenance**. A paragraph should know that it is Clause 2 of Article 5 and also that it came from page 3, block 17, bounding box X.

## 5. Adapter architecture

```text
DocumentParser interface
    parse(file) -> ProviderParseResult

Adapters:
- MinerUAdapter
- MarkerAdapter
- DoclingAdapter
- PPStructureAdapter
- PyMuPDFBaselineAdapter

Normalizer:
ProviderParseResult -> CanonicalDocument
```

Provider-specific fields are allowed only inside a namespaced `debug/provider_metadata` artifact. Business logic must not read them.

## 6. PDF routing

Do not route solely on `has_text`.

The inspector should compute signals such as:

- number of pages;
- extractable-character density per page;
- percentage of pages with usable text;
- replacement/control-character ratio;
- suspicious mojibake/encoding signals;
- text-box coverage;
- embedded-image coverage;
- text quality heuristic;
- page rotation;
- encryption/password state.

Initial route labels:

- `born_digital_good_text`
- `born_digital_suspicious_text`
- `scanned`
- `mixed`
- `unsupported`

Mixed PDFs may be routed per page rather than per file once required by benchmarks.

## 7. Vietnamese administrative semantic layer

This layer is owned by MamaGift rather than by the foundation parser.

Expected entities/relations include:

- document type;
- document number;
- issuing organization;
- issue date;
- effective date if stated;
- title/subject;
- recipients;
- signer/name/title;
- Chapter / Chương;
- Section / Mục;
- Article / Điều;
- Clause / Khoản;
- Point / Điểm;
- appendix;
- deadline;
- obligation/action;
- responsible party;
- referenced document;
- supersedes/amends/replaces relationships when explicitly supported by text.

No inferred legal status should be asserted without source evidence.

## 8. Retrieval architecture

### Stage A: single-document Q&A

Use hierarchy-aware chunks from one selected document. A chunk must retain all source block IDs.

### Stage B: cross-document RAG

Candidate generation should combine:

- semantic embedding similarity;
- lexical/BM25-style matching for exact legal/admin terms and document numbers;
- metadata filters;
- recency/effective-status signals only when explicitly known;
- reranking.

Retrieval must return source spans before generation begins.

### Generation contract

The LLM receives:

- question;
- bounded retrieved context;
- structured metadata;
- citation identifiers;
- instruction to abstain when evidence is insufficient.

The LLM must never invent citation IDs.

## 9. Processing state machine

Recommended document states:

```text
UPLOADED
  -> INSPECTING
  -> QUEUED_FOR_PARSE
  -> PARSING
  -> NORMALIZING
  -> STRUCTURING
  -> READY_FOR_REVIEW
  -> INDEXING
  -> READY

Failure branches:
  -> PARSE_FAILED
  -> UNSUPPORTED
  -> AI_NODE_UNAVAILABLE (retryable job state, not terminal document state)
```

State transitions are server-controlled and recorded with timestamps.

## 10. Idempotency/versioning

- Original uploads are immutable.
- Parsing creates a `parser_run_id` and never overwrites a previous parse artifact.
- Reprocessing the same document creates a new version.
- Index entries reference a specific parse version.
- User corrections are append-only events that can produce a corrected view without destroying raw model output.

## 11. Failure strategy

### Home node offline

Queue the job and expose `waiting_for_worker` status. Do not mark the document failed.

### Parser crashes on one document

Persist logs/error code and allow retry with same or alternate adapter.

### Critical field low confidence

Keep raw extraction, mark `needs_review`, and show source crop/text to the user.

### Q&A lacks evidence

Return an insufficient-evidence response with the best retrieved citations, not a guessed answer.

## 12. Security boundary

Although this is family-only, the public VM must not expose the home inference server directly. Use a private authenticated tunnel/VPN-style link and an application-level service token. The AI node accepts requests only from the control plane or trusted private network.

## 13. Future meeting module boundary

Meeting assistance will later plug in as another ingestion source:

```text
Audio -> ASR -> TranscriptDocument -> same knowledge/index layer
```

It must not contaminate the PDF architecture now. No meeting-specific code is required before the document product is accepted.
