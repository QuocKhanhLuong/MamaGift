# ADR-001 — Parser selection

- **Status:** PENDING EVIDENCE — the benchmark harness is complete and green; the
  parser decision is deliberately not made.
- **Date:** 2026-08-16
- **Phase:** 1 — PDF parser benchmark and parser decision
- **Supersedes:** nothing
- **Blocks:** Phase 2, which must consume a decided parser strategy

## Decision

**No production parser is selected yet.**

`docs/04_PHASE_PLAN.md` requires evidence from at least 30 representative real
Vietnamese administrative documents before a parser route is locked. That corpus is
private and is not present in this repository, so the honest outcome of this phase is
a complete, tested benchmark harness plus an explicitly open decision.

| Slot | Decision | Status |
|---|---|---|
| Primary born-digital parser | **undecided** | pending private-corpus benchmark |
| Primary scanned-document route | **undecided** | pending private-corpus benchmark |
| Fallback strategy | provisional, see below | pending confirmation |
| PyMuPDF role | low-level PDF inspection, routing and rendering utility | **decided** |

Choosing MinerU, Marker, Docling or PP-StructureV3 now would be a decision from
reputation, which `docs/09_CODEX_EXECUTION.md` section 4 forbids for exactly this
choice. No such selection was made.

### What *is* decided

1. **PyMuPDF is the PDF inspection and routing utility, and the baseline only.** It is
   the sole parser in the mandatory CI path. Its measured structure results below rule
   it out as a production parser for structured administrative documents unless a
   future benchmark contradicts that.
2. **All five candidates sit behind one `DocumentParser` interface.** No product code
   imports a provider. Swapping the production parser after the private benchmark is a
   registry change, not a rewrite.
3. **Routing is a separate, independently measured layer.** The route decides which
   parser *capability* is required (`ocr`, `born_digital_text`, `ocr_and_text`), never
   which parser by name.

### Provisional fallback strategy

To be confirmed, not yet evidence-backed:

1. Route the document (`inspect_pdf`).
2. Born-digital route: primary born-digital parser; on `provider_failure` or
   `parse_timeout`, retry once, then fall back to the PyMuPDF baseline and mark the
   document `requires_user_review`.
3. Scanned / garbled route: OCR-capable parser. There is no text-layer fallback,
   because the text layer is the thing that is missing or wrong.
4. Mixed route: per-page capability selection.
5. `encrypted` and `unsupported`: no parsing is attempted. Both surface as structured
   errors (`encrypted_pdf`, `invalid_pdf`) for the user to act on.

## Context

PDF parsing is the highest-risk dependency of the first release. The failure that
matters is not a crash but a plausible-looking wrong answer: a corrupted `Điều`
sequence, a running header pulled into body text, or a wrong date on a deadline.

Generic English document-AI benchmarks do not measure any of that on Vietnamese
administrative documents, so the project builds its own.

## Measured results so far

### Scope and honesty boundary

Everything below was measured on the **eight committed synthetic fixtures**, not on
real documents. The synthetic corpus was written to exercise the harness. It is:

- far smaller than the required 30;
- cleaner than real scans;
- authored by the same project that wrote the metrics.

**These numbers justify no parser choice.** They are recorded because they are real
measurements of real code, and because they already say something useful about the
baseline.

Nothing has been measured for MinerU, Marker, Docling or PP-StructureV3. Those
adapters are implemented and contract-tested against recorded output, but no provider
has been executed. There are no numbers for them, and none are invented here.

### Router

8 of 8 fixtures routed correctly, covering all six labels (`born_digital`, `scanned`,
`mixed`, `garbled_text_layer`, `encrypted`, `unsupported`).

One finding is worth carrying forward: detecting a garbled text layer by Unicode
*category* does not work. A broken CID font map produces wrong-but-real Latin letters
(`ȼ` for `Ủ`), which pass every category check. The router therefore checks membership
in the actual Vietnamese repertoire, which catches it. Real documents will test this
harder than the fixture does.

### PyMuPDF baseline — `pymupdf 1.28.2 (mupdf 1.28.2)`

| Dimension | Score | Reading |
|---|---|---|
| structure_correctness | 0.647 | dragged down by headings/lists/tables |
| critical_field_correctness | 1.000 | on labelled synthetic fixtures |
| text_fidelity | 1.000 | CER 0.0, diacritics fully preserved |
| scan_robustness | n/a | no ground truth on the scanned fixtures |
| runtime_cost | 1.000 | only candidate measured |
| integration_simplicity | 1.000 | declared, not measured |
| **weighted score** | **0.882** | over 0.90 of 1.00 available weight |

Per-metric, on the three labelled documents:

| Metric | Score |
|---|---|
| character_accuracy | 1.000 |
| word_accuracy | 1.000 |
| diacritic_preservation | 1.000 |
| reading_order_accuracy | 1.000 |
| page_attribution_accuracy | 1.000 |
| provenance_completeness | 1.000 |
| header_footer_leakage (1 − leakage) | 1.000 |
| heading_hierarchy_f1 | **0.000** |
| list_preservation | **0.000** |
| table_structure_score | **0.000** |

#### Measured strengths

- **Text fidelity and Vietnamese Unicode**: no character errors, no diacritic loss,
  NFC-normalized output.
- **Provenance**: every block keeps its page number, a unique per-page reading order
  and a bounding box. This is a hard gate, and PyMuPDF passes it.
- **Reading order**: correct on single-column administrative layouts.
- **Speed**: ~2 ms/page on born-digital fixtures; ~28 ms/page on image-heavy pages.
- **Error mapping**: encrypted and malformed inputs produce structured errors rather
  than crashes.

#### Measured weaknesses

- **No semantic block types.** Everything is `text`. Headings, list items and tables
  all score 0.000 because the information does not exist in the output, not because it
  was ranked wrongly. This is the disqualifying weakness for a product built on
  `Chương/Mục/Điều/Khoản/Điểm` hierarchy.
- **No table extraction.** No cell grid at all.
- **No OCR.** On the scanned fixture it returns zero blocks and the weighted score
  simply has nothing to measure.
- **Header/footer separation is not PyMuPDF's.** The 1.000 leakage score comes from
  the normalizer's geometric margin-band heuristic, which is recorded in block
  attributes as `classified_by: normalizer_geometry`. Credit belongs to the
  normalizer, and the heuristic will be far less reliable on real scanned layouts.

### Exact versions and configuration

Measured and recorded in every run artifact:

```text
python                3.12.10
pymupdf               1.28.2 (mupdf 1.28.2)
pymupdf-fonts         1.0.5          # fixture generation only
adapter               pymupdf/1.0, contract 1.0
configuration         {}             # hash 44136fa355b3678a
device                cpu
canonical schema      1.0
router                1.0
normalizer            1.0
metrics               1.0
scoring               1.0
```

Heavy candidates — implemented, contract-tested, **never executed**:

| Adapter | Provider package | Version | Default configuration |
|---|---|---|---|
| `mineru` | `mineru` | not installed | `backend=pipeline`, `lang=vi` |
| `marker` | `marker-pdf` | not installed | `output_format=json`, `use_llm=false` (rejected if enabled) |
| `docling` | `docling` | not installed | library defaults |
| `ppstructure` | `paddleocr` | not installed | `lang=vi`, `device` from config |

None is in the lockfile: they pull multi-GB weights and would break the CPU-only CI
budget (`docs/06_CICD.md` section 4). The private benchmark run must pin and record
their exact resolved versions here.

## What must happen before this ADR is decided

1. Assemble ≥30 real Vietnamese administrative PDFs privately, spanning the
   difficulty and route mix in `docs/03_DOCUMENT_PIPELINE.md` section 3.1.
2. Label Level A on all of them, Level B on the structured subset, Level C on a
   representative transcription subset.
3. Install the heavy providers locally and run:

   ```bash
   PYTHONPATH=packages/contracts/python:packages/docpipe/python \
     uv run python -m tools.parser_bench run \
       --manifest /absolute/path/to/private-manifest.jsonl \
       --parsers pymupdf,mineru,marker,docling,ppstructure \
       --output artifacts/parser-bench/<run-id>
   ```

4. Commit `summary.json` and `summary.md` only. Never the source PDFs, never text
   excerpts containing personal data.
5. Rewrite the Decision section with the winners, and set the status to ACCEPTED.

Hybrid routing is explicitly allowed. There is no requirement that one engine parse
every PDF.

## Unresolved risks

1. **The decision is open, and Phase 2 depends on it.** Phase 2's pipeline has a
   "selected parser/fallback" step with nothing selected. Building Phase 2 against a
   guessed parser is the specific failure this phase exists to prevent.
2. **The synthetic corpus flatters every candidate.** Clean single-column pages,
   rasterized-from-digital "scans", no stamps over text, no photocopy noise, no skew.
   Real documents will move the scores, probably a lot.
3. **Scan robustness is entirely unmeasured**, and it carries 10% of the weight plus
   the whole OCR route. The scanned fixtures have no Level C ground truth.
4. **`integration_simplicity` is a judgement, not a measurement.** It is 5% of the
   weight and it is declared. Documented here so nobody mistakes it for evidence.
5. **Heavy-adapter provider APIs are unverified against a real install.** MinerU,
   Marker, Docling and PaddleOCR all move fast. The translation functions are unit
   tested against recorded payloads in each provider's documented output shape, but the
   *call* into each provider has never executed. Expect breakage on first real run.
6. **The contract recordings are synthetic** and live in `tests/fixtures/recordings/`
   flagged `not_benchmark_evidence`. They must never be pointed at by a benchmark
   manifest.
7. **Vietnamese OCR quality is the open question that matters most** and cannot be
   answered without real scans. If recognition turns out to be the bottleneck rather
   than layout, `docs/04_PHASE_PLAN.md` Phase 6 (PaddleOCR fine-tuning) becomes
   relevant — but only after the failure analysis says so.
8. **The margin-band header/footer heuristic** (7% of page height) is tuned to the
   synthetic fixtures. Real documents with tall letterheads or footnotes will
   misclassify.
9. **Critical-field extraction is deliberately minimal** — regexes for `Số:`,
   Vietnamese dates, `V/v` and deadlines, scoped to benchmark metrics only. It is not
   the Phase 2 administrative parser and must not be promoted into one.

## Consequences

- Phase 1 delivers the harness, the interface, the router, the canonical schema and
  the CI gates. It does not deliver a parser decision.
- Phase 2 is blocked on a private benchmark run, not on more code.
- Because every provider sits behind `DocumentParser`, the eventual decision changes a
  registry entry and a configuration, not the pipeline.
- Phase 2 consumes this open decision through a configurable parser strategy rather
  than waiting for it; see `docs/decisions/ADR-002-ingestion-parser-strategy.md`.
  Until this ADR is decided, every Phase 2 parse run is marked `degraded` and flagged
  for user review, and production environments refuse to parse at all.

## References

- `docs/03_DOCUMENT_PIPELINE.md` — candidates, metrics, weighting, hard gates
- `docs/04_PHASE_PLAN.md` — Phase 1 deliverables and exit criteria
- `docs/05_TEST_STRATEGY.md` — severity model, test data policy
- `docs/08_API_AND_DATA_CONTRACTS.md` — CanonicalDocument v1
- `benchmarks/parser/README.md` — corpus and private-run instructions
- `tools/parser_bench/README.md` — harness internals
- `docs/decisions/ADR-002-ingestion-parser-strategy.md` — how Phase 2 consumes this
  open decision without guessing
