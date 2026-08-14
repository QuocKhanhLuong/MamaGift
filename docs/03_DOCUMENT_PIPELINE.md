# Document Pipeline and Parser Benchmark

## 1. Why this document exists

PDF parsing is the highest-risk technical dependency of the first MamaGift release. The project must not commit to a parser based on generic English benchmarks or convenience.

The production parser is selected only after a project-specific benchmark on Vietnamese administrative/legal PDFs.

## 2. Candidate engines

Required benchmark candidates:

1. **MinerU** — strong document layout / reading-order candidate.
2. **Marker** — strong born-digital conversion and optional LLM-assisted repair.
3. **Docling** — strong structured document representation and layout/table pipeline.
4. **PaddleOCR / PP-StructureV3** — OCR/layout specialist, especially for scanned Vietnamese documents.
5. **PyMuPDF baseline** — retained only as a lightweight baseline and low-level PDF utility.

Additional candidates may be added only if they have a concrete hypothesis and adapter implementation cost is bounded.

## 3. Benchmark corpus

### 3.1 Minimum initial corpus

Start with 30 real PDFs for engineering comparison, then grow toward 100+ documents before locking a long-term production choice.

The initial 30 should intentionally include:

- clean born-digital official letters;
- legal documents with Article/Clause/Point hierarchy;
- multi-page plans;
- PDFs with headers/footers and page numbers;
- tables;
- appendices;
- scans;
- photocopy-like low contrast;
- rotated/skewed pages;
- mixed PDFs containing both digital and scanned pages;
- documents with stamps/signatures overlapping nearby text.

Do not commit private/raw family documents to the public repository. Store only sanitized fixtures or synthetic equivalents in Git.

### 3.2 Difficulty labels

Each benchmark document receives:

```text
easy
medium
hard
```

and route labels:

```text
born_digital
scanned
mixed
```

## 4. Ground-truth layers

Do not label every character manually at first. Use progressive ground truth.

### Level A — document invariants

- page count;
- expected document number;
- issue date;
- title;
- issuing organization;
- signer where present;
- known explicit deadlines.

### Level B — structure

- top-level heading order;
- Article sequence;
- Clause sequence;
- Point sequence;
- list order;
- table presence and major cell content;
- appendix boundaries.

### Level C — text fidelity

For a representative subset, maintain exact transcription to compute CER/WER.

## 5. Metrics

### 5.1 Text metrics

- Character Error Rate (CER) on labeled pages/lines.
- Word Error Rate (WER) on labeled pages/lines.
- Unicode normalization correctness for Vietnamese diacritics.

### 5.2 Structure metrics

- reading-order accuracy;
- heading hierarchy accuracy;
- Article/Clause/Point sequence accuracy;
- list preservation;
- table detection accuracy;
- table structure/cell fidelity on labeled tables;
- header/footer leakage rate;
- page attribution accuracy.

### 5.3 Critical-field metrics

Exact match or normalized exact match for:

- document number;
- issue date;
- explicit deadline;
- issuer;
- title;
- signer.

Critical date/number errors receive greater release severity than ordinary body-text character errors.

### 5.4 Operational metrics

- parse wall time per page;
- peak RAM;
- GPU VRAM if applicable;
- cold-start time;
- artifact size;
- failure rate;
- reproducibility across two identical runs.

## 6. Weighted selection score

Do not let one scalar hide catastrophic failures, but use a weighted summary for comparison.

Suggested initial weighting:

```text
30% structure correctness
25% critical-field correctness
20% text fidelity
10% scan robustness
10% runtime/resource cost
 5% integration/operational simplicity
```

Hard gates still apply:

- no systematic reading-order corruption;
- every useful block must retain page provenance;
- unacceptable critical-date errors disqualify a configuration regardless of average score.

## 7. Benchmark harness contract

Recommended CLI shape:

```bash
python -m tools.parser_bench run \
  --manifest benchmarks/parser/manifest.jsonl \
  --parsers pymupdf,mineru,marker,docling,ppstructure \
  --output artifacts/parser-bench/<run-id>
```

Outputs:

```text
artifacts/parser-bench/<run-id>/
  run.json
  summary.json
  summary.md
  per_document.csv
  parsers/
    <parser>/
      <document-id>/
        canonical.json
        provider-output/
        metrics.json
```

CI does not run all heavyweight parsers. The full benchmark is a manual/release workflow. CI validates the harness on small sanitized fixtures using lightweight/mocked adapters.

## 8. Provider adapter requirements

Every adapter must expose:

```text
name
version
capabilities
parse(input, options) -> ProviderParseResult
healthcheck()
```

The adapter must record:

- exact package/model version;
- relevant config;
- CPU/GPU device;
- start/end duration;
- warnings/errors.

## 9. Canonical normalization requirements

Normalization converts provider output into `CanonicalDocument`.

The normalizer must:

- preserve page numbers;
- preserve block bounding boxes when available;
- assign stable per-run block IDs;
- produce reading-order indexes;
- normalize whitespace/Unicode without destroying source text;
- distinguish semantic cleanup from raw provider output;
- retain confidence when provider supplies it;
- mark fields as unavailable rather than inventing values.

## 10. PDF inspection/router benchmark

The router itself requires tests.

Create a labeled set of PDFs for:

- good digital text;
- corrupt/garbled text layer;
- scan;
- mixed pages;
- password/encrypted;
- malformed/unsupported.

Measure routing accuracy independently from parser quality.

The first router may be heuristic. It should output both label and diagnostic signals so failure cases can be understood.

## 11. Vietnamese administrative parser

Run after canonical normalization, not inside provider adapters.

### 11.1 Deterministic extraction first

Use layout/text rules for high-precision patterns where appropriate:

- `Số:` / document number;
- Vietnamese date expressions;
- `Điều`, `Khoản`, `Điểm` hierarchy;
- common administrative headings;
- `Nơi nhận`;
- signer region hints.

### 11.2 Model-assisted extraction later

LLM/VLM extraction may complement rules for:

- obligations;
- responsible parties;
- explicit deadlines expressed in prose;
- relationships to referenced documents.

Any model-derived structured field retains source block IDs and confidence/review state.

## 12. Human correction loop

UI corrections produce immutable feedback events:

```text
field_name
raw_value
corrected_value
source_block_ids
source_crop_reference
parser/model version
user confirmation
created_at
```

Corrections affect the corrected document view immediately but do not mutate raw parser artifacts.

## 13. Parser-selection outcome

At the end of the benchmark phase, produce an ADR-like result:

```text
Primary born-digital parser: <winner>
Primary scanned parser: <winner>
Fallback parser: <winner>
PyMuPDF role: low-level PDF inspection/rendering only, unless benchmark says otherwise
```

Hybrid routing is explicitly allowed. There is no requirement that one engine parse every PDF.

## 14. Optimization order

When failures occur, optimize in this order:

1. routing;
2. input preprocessing/configuration;
3. provider configuration;
4. Vietnamese domain post-processing;
5. targeted fallback/VLM verification;
6. offline fine-tuning using verified corrections;
7. only then consider replacing foundation components.

This prevents premature custom-model work.
