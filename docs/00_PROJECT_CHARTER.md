# Project Charter

## Product statement

MamaGift is a family-only administrative copilot for Vietnamese school-management documents. Its first responsibility is not to be a general chatbot; it is to turn incoming PDFs into a trustworthy, structured, searchable institutional memory.

## Primary user problem

A school principal receives many administrative documents and must repeatedly answer practical questions such as:

- What does this document require the school to do?
- Which deadlines matter?
- Who is affected?
- Which unit or person is responsible?
- Which article/clause supports the answer?
- Is this document newer than or superseding an older one?

The system must preserve enough provenance to let the user verify every important answer against the original PDF.

## Product invariants

1. **Grounded over fluent.** A concise answer with traceable evidence is better than a confident unsupported answer.
2. **Structure is data.** Chapter/section/article/clause/point hierarchy, tables, page numbers, and source coordinates must not be flattened away unnecessarily.
3. **Parse once, reuse many times.** Parsing/OCR is an ingestion concern. Q&A should consume a normalized document representation rather than reparsing the file.
4. **Knowledge is external to LLM weights.** New documents become searchable immediately through ingestion/indexing. The LLM is not retrained for every new document.
5. **Learning is feedback-driven.** OCR/parser model updates happen offline only after collecting verified corrections and passing regression benchmarks.
6. **Small-user simplicity.** Design for 3–4 users. Avoid infrastructure whose only justification is scale.
7. **Fail visibly.** Low-confidence fields, unavailable home inference, unsupported PDFs, and parse failures must become explicit states rather than silent fallbacks.
8. **Foundation tools are replaceable.** MinerU/Marker/Docling/PP-Structure are adapters behind a common contract, not hardwired into business logic.

## Success definition for the first usable release

A family user can:

1. upload a Vietnamese administrative PDF;
2. see processing status;
3. open the original PDF next to a structured extracted representation;
4. inspect document metadata and hierarchy;
5. ask a question about the document;
6. receive an answer with page/block citations;
7. correct an important extracted field when necessary;
8. find the document later by metadata or search.

## Quality targets

Targets are release gates, not claims about current performance. They are measured on a frozen project benchmark set.

### Parsing/OCR

- No catastrophic page-order corruption on the release benchmark.
- Critical fields (document number, issue date, explicit deadline) target >= 99% exact-match accuracy on supported-quality documents.
- Heading/list hierarchy target >= 95% structure accuracy on supported-quality documents.
- Every extracted block retains page provenance.
- Low-confidence critical fields are surfaced for review rather than silently accepted.

### Retrieval/Q&A

- Citation coverage: 100% of factual answer bullets that depend on document content must cite at least one source span/block.
- Retrieval recall target >= 95% on the curated question set for answer-bearing blocks.
- No-answer behavior is preferred when evidence is insufficient.

### Reliability

- An uploaded file has a durable job state.
- Home AI node downtime does not lose documents or corrupt jobs.
- Jobs can be retried idempotently.

## Supported document classes for the first release

Prioritize:

- official letters / công văn;
- plans / kế hoạch;
- decisions / quyết định;
- notices / thông báo;
- guidance documents;
- Vietnamese legal/administrative documents with Article/Clause/Point structures;
- PDFs containing tables or appendices.

Unsupported or best-effort initially:

- handwriting-heavy pages;
- photograph-only documents with severe perspective distortion;
- encrypted/password-protected PDFs;
- damaged PDFs;
- highly graphical brochures.

## Decision log seed

| Decision | Current position | Revisit when |
|---|---|---|
| Primary input | PDF first | DOCX volume becomes material |
| Parser | Benchmark before choosing | End of Phase 1 |
| OCR foundation | PaddleOCR/PP-Structure candidate | Benchmark says otherwise |
| LLM | Self-hosted OpenAI-compatible Qwen-family endpoint preferred | Hardware/quality benchmark changes |
| Public compute | Small VM | Measured workload exceeds it |
| Heavy inference | Windows home AI node | Reliability/cost requires migration |
| Vector DB | Postgres + pgvector when cross-document RAG starts | Scale or retrieval experiment requires another engine |
| Meeting assistant | Deferred | Document product is stable and used |

## Non-goals for the planning baseline

- Building a Vietnamese OCR architecture from scratch.
- Training a custom LLM from scratch.
- Real-time collaborative editing.
- Enterprise identity, billing, organizations, RBAC hierarchy.
- Meeting transcription.
- Autonomous actions on behalf of the school.

## Definition of done for any phase

A phase is done only when:

- its `/goal` is satisfied;
- all acceptance criteria pass;
- phase-required automated tests are green;
- required benchmark artifacts are generated;
- documentation is updated to reflect actual behavior;
- the next phase does not depend on undocumented assumptions.
