# Phase 5 — archive retrieval baseline comparison

Generated: 2026-08-27

Backend: SQLite (in-memory)

Cases: 19 (synthetic, sanitized, born-digital)

Every number below is measured by `tools/eval/archive_baseline.py` on the fixture
corpus in `tests/fixtures/archive/`. The corpus is synthetic: it contains no real
school, person or document, and it makes no claim about scanned-PDF behaviour, which
remains blocked on ADR-001.

The retrieval stack is deterministic here -- a fake embedding provider and a fake
reranker -- so these numbers measure the RETRIEVAL PLUMBING (filters, fusion,
current-version isolation, identifier handling), not the quality of a real embedding
model or a real cross-encoder. Read the leakage rows as correctness gates and the
recall rows as a regression baseline, not as production quality.

## What these numbers do and do not settle

**Settled — the correctness gates hold in every mode.** Stale-version leakage and
wrong-document leakage are 0.0 across lexical, dense, hybrid and hybrid+reranker, and
metadata-filter accuracy is 1.0. The corpus deliberately contains a superseded parse
version and documents outside each filter, so those zeros are measured, not vacuous.

**Not settled — whether reranking improves ranking.** The reranker used here is
`FakeReranker`, a deterministic shuffle with no semantic signal. The table below shows
`hybrid_rerank` scoring *lower* than `lexical` and `dense` on Recall@3/@5/@10, MRR and
nDCG. That is the expected behaviour of a stub reordering already-good results at
random, and it is evidence about the stub, not about the production cross-encoder.
No claim is made in either direction; answering it requires running this same harness
against a real reranker, which needs the self-hosted worker and is offline operator
evidence, not a CI gate.

The API serves `CrossEncoderReranker` outside the test environment precisely because
the fake is measurably worse than no reranking at all.

**Not settled — real-model retrieval quality.** Embeddings here are deterministic
hashes, not BGE-M3. Recall numbers measure whether the plumbing returns the right
rows, not whether a real embedding model would rank them well.

# Archive Retrieval Baseline Comparison

## Overall Mode Metrics

| Mode | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR | nDCG@10 | Ident. Acc | Filter Acc | Stale Leak | Wrong Leak | P50 (ms) | P95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `lexical` | 0.8947 | 1.0000 | 1.0000 | 1.0000 | 0.9737 | 0.9764 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 1.03 | 7.54 |
| `dense` | 0.8947 | 1.0000 | 1.0000 | 1.0000 | 0.9737 | 0.9764 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 4.95 | 11.72 |
| `hybrid` | 0.8947 | 0.9474 | 1.0000 | 1.0000 | 0.9605 | 0.9658 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 6.32 | 19.18 |
| `hybrid_rerank` | 0.8947 | 0.9211 | 0.9474 | 0.9474 | 0.9474 | 0.9409 | 0.9091 | 1.0000 | 0.0000 | 0.0000 | 6.99 | 25.55 |

## Per Document Type Slices

### Document Type: `Công văn`

| Mode | Recall@1 | Recall@5 | Recall@10 | MRR | nDCG@10 | Case Count |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `lexical` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 2 |
| `dense` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 2 |
| `hybrid` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 2 |
| `hybrid_rerank` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 2 |

### Document Type: `Kế hoạch`

| Mode | Recall@1 | Recall@5 | Recall@10 | MRR | nDCG@10 | Case Count |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `lexical` | 0.9167 | 1.0000 | 1.0000 | 1.0000 | 0.9866 | 6 |
| `dense` | 0.9167 | 1.0000 | 1.0000 | 1.0000 | 0.9866 | 6 |
| `hybrid` | 0.9167 | 1.0000 | 1.0000 | 1.0000 | 0.9866 | 6 |
| `hybrid_rerank` | 0.9167 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 6 |

### Document Type: `Nghị định`

| Mode | Recall@1 | Recall@5 | Recall@10 | MRR | nDCG@10 | Case Count |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `lexical` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 2 |
| `dense` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 2 |
| `hybrid` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 2 |
| `hybrid_rerank` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 2 |

### Document Type: `Quyết định`

| Mode | Recall@1 | Recall@5 | Recall@10 | MRR | nDCG@10 | Case Count |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `lexical` | 0.7000 | 1.0000 | 1.0000 | 0.9000 | 0.9262 | 5 |
| `dense` | 0.7000 | 1.0000 | 1.0000 | 0.9000 | 0.9262 | 5 |
| `hybrid` | 0.7000 | 1.0000 | 1.0000 | 0.8500 | 0.8861 | 5 |
| `hybrid_rerank` | 0.7000 | 0.8000 | 0.8000 | 0.8000 | 0.7754 | 5 |

### Document Type: `Thông tư`

| Mode | Recall@1 | Recall@5 | Recall@10 | MRR | nDCG@10 | Case Count |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `lexical` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 4 |
| `dense` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 4 |
| `hybrid` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 4 |
| `hybrid_rerank` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 4 |
