# Parser benchmark corpus

This directory holds the **sanitized synthetic** benchmark corpus and the manifests
that point at it. No real school or family document may ever be committed here
(`docs/03_DOCUMENT_PIPELINE.md` section 3.1).

## Layout

```text
benchmarks/parser/
  manifest.jsonl          # public synthetic manifest, committed
  fixtures/               # synthetic PDFs, committed
  ground_truth/           # authored ground truth for the labelled fixtures
  recordings/             # real provider recordings captured locally (not committed)
  generate_fixtures.py    # regenerates fixtures + ground truth + manifest
```

## Manifest format

JSONL, one benchmark document per line:

```json
{
  "document_id": "cong_van_born_digital",
  "path": "benchmarks/parser/fixtures/cong_van_born_digital.pdf",
  "route_label": "born_digital",
  "difficulty": "easy",
  "provenance": "synthetic",
  "ground_truth": "benchmarks/parser/ground_truth/cong_van_born_digital.json",
  "notes": "..."
}
```

- `route_label`: `born_digital` | `scanned` | `mixed` | `garbled_text_layer` |
  `encrypted` | `unsupported`
- `difficulty`: `easy` | `medium` | `hard`
- `provenance`: `synthetic` | `sanitized` | `private`

Entries marked `private` **must** use an absolute path outside the repository; the
manifest validator rejects anything else.

## Ground truth is progressive

Not every document needs every layer. A missing layer makes its metrics report
*unavailable*; it never scores zero, because a missing label is not a parser failure.

- **Level A — invariants**: `page_count`, `critical_fields`.
- **Level B — structure**: `reading_order`, `headings`, `lists`, `tables`,
  `header_footer_texts`.
- **Level C — text fidelity**: `transcript`, keyed by page number as a string.

Ground truth is authored from the source document, never copied from parser output.
`generate_fixtures.py` writes the PDF and its ground truth from one shared definition
for exactly this reason.

## Current committed corpus

Eight synthetic documents covering every router label:

| Document | Route | Difficulty | Ground truth |
|---|---|---|---|
| `cong_van_born_digital` | born_digital | easy | A + B + C |
| `quyet_dinh_dieu_khoan` | born_digital | medium | A + B + C |
| `trang_xoay` | born_digital (rotated) | medium | A + B + C |
| `text_layer_hong` | garbled_text_layer | hard | route only |
| `scan_khong_co_text` | scanned | medium | route only |
| `ho_so_hon_hop` | mixed | hard | route only |
| `tai_lieu_ma_hoa` | encrypted | hard | route only |
| `tep_khong_hop_le` | unsupported | hard | route only |

This corpus exercises the harness. **It is not sufficient to choose a parser.**
`docs/04_PHASE_PLAN.md` requires at least 30 representative real documents, and the
report prints that shortfall explicitly on every run.

The encrypted fixture uses the documented, non-secret password `mamagift-fixture`.

## Regenerating fixtures

```bash
make parser-fixtures
```

## Running the benchmark

Lightweight, the same thing CI runs:

```bash
make parser-benchmark-smoke
make parser-bench                       # pymupdf only, writes artifacts/parser-bench/local
```

Any subset of adapters:

```bash
PYTHONPATH=packages/contracts/python:packages/docpipe/python \
  uv run python -m tools.parser_bench run \
    --manifest benchmarks/parser/manifest.jsonl \
    --parsers pymupdf,mineru,marker,docling,ppstructure \
    --output artifacts/parser-bench/$(date +%Y%m%dT%H%M%SZ)
```

Adapters whose provider is not installed fail with `provider_unavailable` and do not
stop the other candidates.

## Private corpus runs

The real Vietnamese administrative corpus is private and stays outside Git. Write a
local manifest, e.g. `~/mamagift-private/manifest.jsonl`:

```json
{"document_id": "private_001", "path": "/absolute/path/to/doc.pdf", "route_label": "born_digital", "difficulty": "medium", "provenance": "private", "ground_truth": "/absolute/path/to/gt.json", "notes": ""}
```

Then run the benchmark against it locally. Commit only the derived
`summary.json` / `summary.md` metrics — never the source PDFs, and never any text
excerpt containing personal data.

## Real provider recordings

`recordings/<parser>/<document_id>.json` holds `ProviderParseResult` payloads captured
from real provider runs, for replaying a heavy parser without reinstalling it. These
are not committed.

Do not confuse them with `tests/fixtures/recordings/`, which contains hand-authored
contract fixtures that are explicitly **not** benchmark evidence.
