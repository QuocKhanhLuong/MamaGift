# Data, Feedback, and Continual Learning

## 1. Two different meanings of “learning”

MamaGift deliberately separates:

### Knowledge ingestion

New PDF -> parse -> normalize -> index -> immediately queryable.

This solves knowledge freshness and avoids LLM knowledge-cutoff problems for uploaded documents.

### Model adaptation

Verified OCR/parser corrections -> reviewed dataset -> offline fine-tuning -> frozen benchmark -> optional model promotion.

This improves document-reading skill. It is not how new administrative knowledge is stored.

## 2. Data classes

### A. Original source

- immutable PDF bytes;
- SHA-256 checksum;
- upload metadata;
- original filename;
- MIME type;
- page count once known.

### B. Raw provider output

Exact or minimally transformed output from MinerU/Marker/Docling/PP-Structure/etc. Versioned by parser run.

### C. Canonical document

Provider-independent normalized representation used by the application.

### D. Semantic extraction

Administrative fields/hierarchy/obligations/deadlines with provenance.

### E. Search index

Derived and reproducible from a particular canonical parse version.

### F. Feedback events

Append-only verified user corrections.

### G. Training dataset versions

Private exports derived from reviewed feedback plus approved source crops/labels.

## 3. Immutability and lineage

Never mutate historical inference results in place.

Lineage:

```text
source PDF
  -> parser_run v1
      -> canonical v1
          -> index v1
          -> correction events
  -> parser_run v2
      -> canonical v2
          -> index v2
```

The current application view may overlay verified corrections, but raw artifacts remain recoverable.

## 4. Feedback event design

A correction should capture enough information to become future training data and to debug why the old system failed.

Suggested fields:

```text
feedback_id
user_id
document_id
parser_run_id
block_id / field_id
feedback_type
raw_prediction
corrected_value
source_page
source_bbox
source_crop_object_key (optional)
parser_name
parser_version
model_name/model_version
original_confidence
created_at
review_status
```

Feedback types may include:

```text
critical_field_correction
ocr_text_correction
hierarchy_correction
reading_order_correction
metadata_correction
retrieval_feedback
answer_feedback
```

Do not automatically treat every user edit as training ground truth until the feedback type is reviewable and semantics are clear.

## 5. Active-learning behavior

Prefer requesting review where the expected value is highest:

- low-confidence critical dates/numbers;
- disagreement between two extraction methods;
- unusual character patterns;
- OCR confidence outliers;
- structure breaks around `Điều/Khoản/Điểm`;
- document types underrepresented in benchmark data.

Do not annoy the user by asking for confirmation on every field.

## 6. Private dataset export

Because the repository is public, real training data must live outside Git.

Export format should be deterministic and manifest-driven.

Example:

```text
mamagift-dataset-2026-09-01/
  manifest.jsonl
  images/
  labels/
  metadata.json
```

Each sample must include a source document identifier and split group to prevent same-document leakage.

## 7. Train/validation/test splitting

Split at **document level**, never random line/crop level only.

Reason: many text lines from the same administrative template are near-duplicates. Random line splits produce misleadingly high accuracy.

Recommended:

```text
train: reviewed historical documents
validation: held-out documents
frozen test: manually curated documents never used for model selection/training
```

Maintain challenge slices:

- low-quality scan;
- table;
- red stamp/signature overlap;
- small font;
- skew/rotation;
- rare document-number formats;
- dates/deadlines;
- Vietnamese diacritic-heavy text.

## 8. Offline training workflow

Kaggle/local GPU workflow is intentionally disconnected from production.

```text
1. export reviewed dataset
2. compute dataset checksum/version
3. upload private dataset to training environment
4. fine-tune selected OCR/parser component
5. export candidate checkpoint
6. run frozen benchmark
7. compare candidate vs production
8. produce model card/report
9. manually approve or reject
10. deploy versioned model artifact
```

Training code/config must be reproducible even when the private data itself is not in Git.

## 9. When to fine-tune

Fine-tune only after error analysis indicates a systematic model bottleneck.

Examples that justify OCR recognition adaptation:

- repeated Vietnamese diacritic substitutions;
- repeated digit/letter confusion in document numbers;
- consistent failure for scan/font families;
- confidence is poor despite correct routing/preprocessing.

Do not fine-tune if the dominant failures come from:

- wrong reading order;
- bad page routing;
- table structure;
- incorrect business rules;
- parser normalization bugs.

Fix the correct layer first.

## 10. Synthetic data

Synthetic administrative text is useful for OCR robustness but cannot replace real held-out evaluation.

Potential generation dimensions:

- common Vietnamese administrative headings;
- document numbers;
- dates;
- Times New Roman/Arial-like fonts available legally in training environment;
- multiple DPI values;
- blur;
- compression;
- low contrast;
- mild rotation;
- shadows;
- stamp/signature overlays generated from synthetic shapes, not copied private seals.

Synthetic samples must be labeled as synthetic in the manifest.

## 11. Model registry

Production must pin exact versions.

Model record:

```text
model_id
component_type
base_model
artifact_uri
artifact_checksum
training_code_commit
training_dataset_version
training_config
created_at
benchmark_report
promotion_status
promoted_at
supersedes_model_id
```

No `latest` floating model in production.

## 12. Promotion policy

Candidate promotion compares against current production model on the same frozen benchmark.

Hard requirements:

- no unexplained critical-field regression;
- no catastrophic structure regression;
- reproducible artifact checksum;
- version metadata complete;
- rollback artifact still available.

A lower average CER is insufficient if date/document-number accuracy becomes worse.

## 13. Knowledge freshness

Every new document should become available to archive search after indexing without:

- fine-tuning Qwen;
- restarting the LLM;
- rebuilding the full corpus from scratch.

Indexing must be incremental and version-aware.

For questions that imply “latest”, retrieval should use explicit document metadata and timestamps, not the LLM’s pretrained world knowledge.

## 14. Document relationships

The knowledge layer may represent:

```text
references
amends
replaces
supersedes
implements
related_to
```

Only assert strong legal/administrative relations when explicit text or reviewed metadata supports them. Do not derive legal validity from date alone.

## 15. Dataset and benchmark versioning

Use semantic or date-based versions for:

```text
parser-benchmark-v1
admin-field-benchmark-v1
rag-eval-v1
ocr-training-dataset-2026-09-01
```

Every reported metric names the dataset version and code commit.

## 16. Retention

High-value durable assets:

- source PDFs;
- verified corrections;
- benchmark labels;
- dataset manifests;
- model promotion reports.

Reproducible/lower-priority assets:

- embeddings;
- generated page previews;
- downloaded base model weights;
- caches.

This distinction should guide backup policy.
