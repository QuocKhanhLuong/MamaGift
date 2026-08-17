# Parser benchmark harness

Runs every candidate parser over a manifest of Vietnamese administrative PDFs and
reports the evidence for the Phase 1 parser decision. Nothing here selects a parser.

## Commands

```bash
export PYTHONPATH=packages/contracts/python:packages/docpipe/python

python -m tools.parser_bench validate --manifest benchmarks/parser/manifest.jsonl
python -m tools.parser_bench health   --parsers pymupdf,mineru,marker,docling,ppstructure
python -m tools.parser_bench run \
  --manifest benchmarks/parser/manifest.jsonl \
  --parsers pymupdf,mineru,marker,docling,ppstructure \
  --output artifacts/parser-bench/<run-id>
```

Flags:

- `--adapter-config <file.json>` — per-adapter configuration, keyed by parser name.
  The configuration is hashed into every artifact so a run can be reproduced.
- `--require-success` — exit non-zero if any parse failed. Used by CI smoke jobs, not
  by exploratory runs where failures are the interesting result.

## Output layout

```text
artifacts/parser-bench/<run-id>/
  run.json              # environment, git commit, adapter versions and config hashes
  summary.json          # scores, route confusion matrix, every document run
  summary.md            # human-readable report
  per_document.csv      # one row per (parser, document)
  inspection/<doc>.json # router signals, independent of any parser
  parsers/<parser>/<doc>/
    canonical.json      # CanonicalDocument v1
    provider-output/    # raw provider artifact
    metrics.json
```

## Modules

| Module | Responsibility |
|---|---|
| `manifest.py` | manifest + ground-truth schemas and validation |
| `metrics.py` | text, structure, provenance and critical-field metrics |
| `critical_fields.py` | bounded deterministic extraction, benchmark scoring only |
| `scoring.py` | weighted dimensions and hard gates |
| `runner.py` | per-document execution and artifact persistence |
| `report.py` | `run.json` / `summary.*` / `per_document.csv` generation |

## What the score means

Weighted dimensions (`docs/03_DOCUMENT_PIPELINE.md` section 6):

```text
30% structure correctness
25% critical-field correctness
20% text fidelity
10% scan robustness
10% runtime/resource cost
 5% integration/operational simplicity
```

Only `integration_simplicity` is declared rather than measured, which is why it carries
the smallest weight.

Dimensions with no ground truth are **excluded** and the report prints the resulting
weight coverage. A metric is never silently defaulted to zero.

Hard gates disqualify a configuration regardless of its weighted score:

- reading-order accuracy below 0.70;
- any block losing page provenance;
- any severity-3 critical-field error (document number, issue date, deadline);
- parsing every document unsuccessfully.

## Adding a parser candidate

1. Implement an adapter in `packages/docpipe/python/mamagift_docpipe/adapters/`,
   importing the provider lazily inside `parse`.
2. Register it in `ADAPTER_REGISTRY`.
3. Map provider failures onto `ParserErrorCode`.
4. Add its block vocabulary to `BLOCK_TYPE_ALIASES`.
5. Add a contract recording under `tests/fixtures/recordings/<parser>/`.

The shared contract suite in `tests/contract/` then applies automatically.

## Heavy providers

None of MinerU, Marker, Docling or PaddleOCR is in the lockfile: they pull multi-GB
model weights and would break the CPU-only CI budget. Install them in a separate local
environment when running the real benchmark, and record the exact versions in
`docs/decisions/ADR-001-parser-selection.md`.
