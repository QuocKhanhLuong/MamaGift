# Test Strategy

## 1. Test philosophy

MamaGift is a document-understanding product. The most dangerous failures are not crashes; they are plausible-but-wrong outputs.

Testing therefore covers four dimensions:

1. software correctness;
2. document parsing correctness;
3. retrieval/generation correctness;
4. deployment/recovery correctness.

## 2. Test pyramid

```text
                    Manual real-doc evaluation
                 /                         \
             Browser E2E              RAG eval sets
           /           \              /          \
     Integration     contract      parser      retrieval
       tests           tests       golden       golden
      /   \             |             |            |
 unit tests ------- schema/logic ------- deterministic fixtures
```

CI favors deterministic tests. Heavy GPU/model benchmarks run as explicit release/manual workflows.

## 3. Test data policy

### Public repository fixtures

Allowed:

- synthetic PDFs;
- sanitized samples;
- generated administrative-like Vietnamese documents;
- tiny images/crops without private personal data;
- provider-output recordings produced from sanitized inputs.

Not allowed:

- real private family/school documents;
- student/teacher personal data;
- confidential meeting data.

Private benchmark manifests may reference local paths outside Git.

## 4. Backend unit tests

Cover at minimum:

- request validation;
- document ID/checksum generation;
- storage paths;
- state transitions;
- retry/idempotency rules;
- parser routing heuristics;
- canonical normalization;
- Vietnamese Unicode handling;
- field normalization;
- hierarchy builder;
- citation validation;
- retrieval filters;
- correction-event application.

## 5. Schema/contract tests

Contracts are compatibility boundaries and need direct tests.

### CanonicalDocument

Validate:

- required IDs;
- page numbering;
- block type enum;
- bbox constraints;
- reading-order uniqueness;
- valid parent references;
- provenance present for extracted fields;
- parser/model version metadata.

### Parser adapters

Every adapter must satisfy the same fixture suite.

### AI worker

Contract suite covers health, authentication, job identity, errors, timeouts, model version, and response schema.

### API

Generate/OpenAPI-validate contract where practical and test breaking schema drift.

## 6. Golden document tests

Golden tests compare normalized output against reviewed expected structures.

Do not snapshot gigantic provider JSON. Snapshot the stable canonical representation or selected semantic fields.

Golden cases should include:

- simple công văn;
- quyết định with multiple `Điều`;
- kế hoạch with nested numbering;
- legal-style `Điều/Khoản/Điểm`;
- table;
- appendix;
- scan;
- mixed document;
- malformed/unsupported PDF.

Golden diff output should make hierarchy/order regressions human-readable.

## 7. Parser evaluation metrics

### Text

- CER;
- WER;
- Vietnamese Unicode normalization checks.

### Layout/structure

- reading-order pair accuracy or equivalent sequence metric;
- heading hierarchy precision/recall/F1;
- Article/Clause/Point sequence accuracy;
- list preservation;
- table presence/structure score;
- header/footer leakage;
- page attribution.

### Fields

Exact/normalized match:

- document number;
- issue date;
- deadline;
- issuer;
- title;
- signer.

## 8. Critical severity model

Not all errors are equal.

### Severity 0 — cosmetic

Whitespace, harmless punctuation differences.

### Severity 1 — ordinary text

Body-text typo that does not change meaning materially.

### Severity 2 — structure

Wrong list order, missing heading parent, table ordering corruption.

### Severity 3 — critical fact

Wrong document number, date, deadline, responsible party, or source citation.

Release gates should prioritize preventing Severity 3 regressions even if average CER improves.

## 9. RAG retrieval evaluation

Maintain a curated query set with:

```text
question
expected_document_ids
expected_block_ids or answer-bearing region
metadata filters if any
```

Metrics:

- Recall@1/3/5/10;
- MRR/nDCG if useful;
- exact-document-number retrieval;
- metadata-filter correctness;
- latency.

Separate:

- single-document retrieval;
- cross-document retrieval.

## 10. Generation evaluation

Do not make CI depend on nondeterministic local LLM quality.

### CI contract tests

Use a fake deterministic model to verify:

- only allow-listed citation IDs survive;
- response schema;
- abstention branch;
- prompt context construction;
- retrieved block limits;
- source rendering.

### Offline model evaluation

Run against the actual self-hosted model on a curated QA set.

Human rubric per answer:

```text
0 = wrong/unsupported
1 = partially correct but materially incomplete
2 = correct with minor issue
3 = correct, useful, citations support answer
```

Also score citation correctness separately.

## 11. Prompt-injection/document-content tests

Documents are untrusted content.

Fixtures should contain text such as:

```text
Ignore previous instructions...
Reveal your system prompt...
Call an external service...
```

Expected behavior:

- treated as document content;
- never changes system/tool policy;
- never exposes secrets;
- never creates unsupported actions.

## 12. Frontend tests

### Unit/component

- upload widget;
- status display;
- metadata fields;
- hierarchy viewer;
- correction form;
- chat answer/citation renderer;
- source jump;
- error states.

### Browser E2E

Core journey:

```text
login
-> upload
-> processing
-> document viewer
-> verify/correct field
-> ask question
-> open citation
```

Test common mobile and desktop viewport sizes.

## 13. Database tests

- migrations up from empty;
- migration compatibility against previous schema snapshot when practical;
- uniqueness/idempotency constraints;
- cascade/delete semantics explicitly tested;
- parse versioning;
- feedback append-only behavior;
- vector/index consistency later.

## 14. Job/worker failure tests

Required scenarios:

- worker offline before lease;
- worker disappears during processing;
- duplicate delivery;
- retry after timeout;
- parser process crashes;
- result arrives after lease expiration;
- API restarts while job queued;
- idempotency key replay.

No scenario may silently create two current parse versions for one run.

## 15. Performance tests

Not required on every PR.

Track distributions for:

- upload latency;
- parse sec/page;
- OCR sec/page;
- indexing duration;
- retrieval latency;
- LLM first-token and total answer latency;
- memory/VRAM usage;
- queue wait time.

Define performance budgets after collecting baseline data rather than inventing arbitrary hard limits.

## 16. Continual-learning tests

Before promoting an OCR/parser candidate:

- frozen test set untouched by training;
- no document-level leakage across train/test;
- baseline vs candidate metric diff;
- critical-field regression gate;
- old hard cases rerun;
- model version and dataset version recorded;
- rollback artifact exists.

## 17. Test naming convention

Recommended categories:

```text
tests/unit/
tests/contract/
tests/integration/
tests/golden/
tests/eval/
e2e/
```

Use markers/tags for expensive tests:

```text
unit
integration
heavy
requires_gpu
requires_real_model
private_benchmark
```

Default CI must exclude `requires_gpu`, `requires_real_model`, and `private_benchmark`.

## 18. Phase test matrix

| Phase | Must pass before exit |
|---|---|
| 0 | lint, typecheck, unit smoke, migration, Compose validation |
| 1 | router, parser contracts, canonical schema, benchmark smoke |
| 2 | ingestion integration, admin golden tests, state machine |
| 3 | web components, upload/view/correction E2E |
| 4 | worker contract, single-doc retrieval eval, citation contract |
| 5 | incremental indexing, cross-doc retrieval eval |
| 6 | feedback/export/promotion/regression tooling |
| 7 | deployment smoke, backup/restore, failure drills |

## 19. Flaky-test policy

A flaky test is a bug.

- Do not blindly retry application tests to hide nondeterminism.
- Quarantine only with an issue and owner/reason.
- Network/model-dependent tests should use local fakes in CI.
- E2E waits on explicit states/events, not arbitrary sleeps.

## 20. Definition of a testable feature

A feature is not complete if its success can only be checked manually. Each phase should leave deterministic seams where model/network behavior can be replaced by fixtures/fakes.
