# Infrastructure

## 1. Deployment philosophy

MamaGift has two compute tiers:

1. a small always-on VM for web/API/state;
2. a Windows home AI node for heavy local inference.

The system should remain operable when the home node is unavailable. Heavy jobs wait; data is not lost.

## 2. Initial topology

```text
Internet
  |
  v
DNS / HTTPS
  |
  v
+----------------------------+
| VM                         |
|----------------------------|
| Reverse proxy              |
| Web                        |
| FastAPI                    |
| PostgreSQL                 |
| object/file storage        |
| lightweight queue          |
+-------------+--------------+
              |
       private tunnel
              |
              v
+----------------------------+
| Windows Home AI Node       |
|----------------------------|
| worker service             |
| parser/OCR runtimes        |
| embeddings/reranker        |
| Ollama or compatible LLM   |
+----------------------------+
```

## 3. VM baseline

Start small and measure before scaling.

Recommended initial class:

- Ubuntu LTS;
- 2 vCPU minimum, 4 vCPU preferred if affordable;
- 4 GB RAM minimum;
- 40–80 GB SSD depending on whether originals are stored locally;
- Docker + Docker Compose;
- HTTPS termination;
- automated database backups.

The VM should not require a GPU.

## 4. Service layout

Initial Compose-level services:

```text
web
api
postgres
worker-control      # optional lightweight async worker
reverse-proxy
```

Do not introduce Redis unless a concrete phase needs it. A Postgres-backed job table/polling worker is sufficient for early phases and keeps operations simple.

When background workload proves Postgres polling inadequate, add a queue explicitly as an architectural change.

## 5. Storage

### Original files

Use an abstraction that supports:

- local filesystem in development;
- VM-attached disk for early production;
- S3-compatible object storage later without changing document APIs.

Never store original PDF bytes inside relational database columns.

Recommended object layout:

```text
objects/
  documents/{document_id}/original.pdf
  documents/{document_id}/parses/{parser_run_id}/canonical.json
  documents/{document_id}/parses/{parser_run_id}/provider-output/
  documents/{document_id}/previews/{page}.webp
  documents/{document_id}/feedback/...
```

### Database

PostgreSQL is the production default from the first VM deployment because later phases need metadata queries and pgvector.

SQLite is allowed only for isolated local prototypes/tests.

## 6. Home AI node

The Windows machine is treated as replaceable compute, not the source of truth.

The node may host:

- document parser runtimes that benefit from GPU/local resources;
- PaddleOCR/PP-Structure;
- embedding model;
- reranker;
- Qwen-family model served via Ollama/vLLM/SGLang or another OpenAI-compatible server;
- later ASR.

It must not own canonical database state.

## 7. Home-node API contract

Prefer one internal worker API rather than exposing every model server.

Example internal endpoints:

```text
GET  /health
POST /jobs/parse
POST /jobs/embed
POST /jobs/rerank
POST /llm/chat       # optional proxy
```

Alternative: the VM may call an OpenAI-compatible LLM endpoint directly, but parser/OCR jobs still use a stable worker contract.

Every request has:

- job ID;
- idempotency key;
- model/parser version;
- timeouts;
- structured error codes.

## 8. Connectivity

Requirements:

- no public inbound port required on the home router;
- encrypted tunnel between VM and home node;
- service authentication independent of network location;
- reconnection after Windows reboot;
- health heartbeat visible to the API.

Valid implementation choices include WireGuard/Tailscale/Cloudflare Tunnel-style connectivity. The implementation phase should choose one based on operational simplicity; business code must not depend on the vendor.

## 9. Worker availability semantics

The API tracks worker heartbeat:

```text
ONLINE
DEGRADED
OFFLINE
```

A processing job has independent state:

```text
QUEUED
LEASED
RUNNING
SUCCEEDED
FAILED_RETRYABLE
FAILED_TERMINAL
```

If the worker goes offline mid-job, the lease expires and the job becomes retryable. Retries must be idempotent.

## 10. Model serving

Initial LLM choice is deliberately abstracted.

Preferred operational contract:

```text
OpenAI-compatible /v1/chat/completions
```

This allows switching among Qwen/DeepSeek/other local models without changing application service interfaces.

Model selection is benchmark-driven. The first target should be a model that fits existing Windows GPU memory while meeting Vietnamese administrative QA quality and latency targets.

## 11. Environments

### Local development

- frontend on host or Docker;
- API on host or Docker;
- Postgres in Docker;
- fake AI worker by default;
- optional real parser/LLM profiles.

### CI

- no GPU requirement;
- no external paid API requirement;
- deterministic fixtures;
- mocked/fake inference for application tests;
- parser integrations tested via contract fixtures unless a lightweight CPU smoke test is practical.

### Production

- VM Compose stack;
- Windows AI worker as separate deployment;
- explicit model/parser version configuration.

## 12. Configuration

Use environment variables/secrets for deployment-specific values. Commit `.env.example`, never real credentials.

Expected categories:

```text
APP_ENV
DATABASE_URL
OBJECT_STORAGE_ROOT or S3_*
PUBLIC_BASE_URL
AI_WORKER_URL
AI_WORKER_TOKEN
LLM_BASE_URL
LLM_MODEL
EMBEDDING_MODEL
RERANKER_MODEL
DEFAULT_PARSER
MAX_UPLOAD_MB
```

## 13. Backups

At minimum:

- daily PostgreSQL backup;
- original PDFs included in disk/object-storage backup policy;
- user corrections backed up;
- model checkpoints do not need the same backup priority because they are reproducible/downloadable;
- benchmark labels/ground truth are high-value and must be backed up.

Recovery must be tested before calling production stable.

## 14. Observability

Keep it lightweight:

- structured JSON application logs;
- request ID / job ID correlation;
- processing duration by stage;
- parser/model version;
- queue depth;
- worker heartbeat;
- failure counters;
- disk usage.

A full observability stack is not required initially. A health endpoint and useful logs are required.

## 15. CI/CD deployment policy

CI runs on every PR and push to `main`.

Deployment should be introduced only after the application can start deterministically from Compose. Initial production deployment may be manual-with-script; automated deployment comes after stable tests.

Preferred progression:

1. CI only.
2. Build versioned containers on `main`.
3. Manual VM deploy using immutable image tag.
4. Automated VM deploy after release gates are reliable.
5. Home worker remains independently deployable and versioned.

## 16. Cost-control rules

- no always-on GPU cloud instance;
- no managed vector database initially;
- no Kubernetes;
- no paid LLM dependency required for core operation;
- benchmark CPU vs home-node placement before moving a workload;
- add infrastructure only when a measured bottleneck justifies it.
