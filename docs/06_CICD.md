# CI/CD Plan

## 1. Goals

CI/CD exists to enforce phase contracts without requiring paid APIs, the Windows home machine, private documents, or GPU runners on every pull request.

Principles:

- deterministic PR checks;
- fast feedback for ordinary changes;
- heavy parser/model evaluation separated from mandatory PR CI;
- `main` remains releasable;
- deployment uses immutable artifacts;
- production deploy starts manual and becomes automated only after recovery is proven.

## 2. Branch policy

Recommended:

- `main`: protected integration/release branch;
- feature branches: `phase-<n>/<short-name>`;
- PR required for implementation changes once development begins;
- squash merge preferred for phase tasks unless commit history is intentionally meaningful.

Required branch protection when repository settings allow:

- require pull request;
- require status checks;
- block force push to `main`;
- require branch up to date for release-critical PRs;
- dismiss stale approvals only if collaboration expands beyond the single developer.

## 3. Mandatory PR checks

The exact jobs appear gradually as code exists.

### Always-on repository checks

```text
docs-check
secret-scan
repository-hygiene
```

### Backend

```text
backend-format-check
backend-lint
backend-typecheck
backend-unit
backend-contract
backend-integration
```

### Frontend

```text
frontend-format-check
frontend-lint
frontend-typecheck
frontend-unit
frontend-build
```

### Application integration

```text
db-migration-test
compose-config
web-e2e-smoke
```

### Document pipeline

```text
parser-contract-tests
parser-benchmark-smoke
admin-parser-golden-tests
```

### RAG phases

```text
rag-eval-mini
ai-worker-contract
cross-document-retrieval
```

## 4. CI runtime constraints

Mandatory PR CI must:

- run on standard GitHub-hosted CPU runners;
- use sanitized/synthetic fixtures;
- mock real LLM inference;
- mock or use recorded output for heavyweight parser providers;
- avoid downloading multi-GB weights unless explicitly cached and justified;
- avoid requiring Windows home node connectivity;
- avoid paid network services.

## 5. Workflow layout

Recommended eventual files:

```text
.github/workflows/
  ci.yml
  parser-benchmark.yml
  build-images.yml
  deploy-vm.yml
  release-eval.yml
```

### `ci.yml`

Triggered:

```text
pull_request
push to main
```

Runs mandatory deterministic tests.

### `parser-benchmark.yml`

Triggered manually with `workflow_dispatch`.

Purpose:

- run a public/sanitized parser benchmark that is feasible on available runner;
- optionally support self-hosted runner later;
- upload benchmark reports as artifacts.

Full private-real-document benchmark is run outside public GitHub Actions if data cannot be uploaded safely.

### `build-images.yml`

Triggered after green `main` or tagged release once Dockerized services exist.

Build:

- API image;
- web image if not static-hosted separately;
- optional AI-worker image where Windows/Linux compatibility allows.

Tag with commit SHA. Human-friendly release tags are additional aliases, never the sole immutable identifier.

### `deploy-vm.yml`

Introduced in Phase 7.

Initially `workflow_dispatch` with environment approval.

Deployment should:

1. select immutable SHA-tagged images;
2. backup or verify latest backup state where appropriate;
3. pull images;
4. run migrations in controlled step;
5. restart Compose;
6. run health smoke;
7. report deployed SHA.

### `release-eval.yml`

Manual release gate for:

- parser golden suite;
- larger retrieval eval;
- benchmark artifact comparison;
- optional self-hosted model evaluation.

Do not block ordinary code PRs on GPU availability.

## 6. Path-based optimization

As the repo grows, jobs may use path filters, but correctness is more important than skipping work.

Examples:

- docs-only changes can skip frontend/backend builds after repository checks;
- parser changes trigger parser contracts/golden tests;
- migration changes always trigger DB migration integration;
- shared contract changes trigger both backend and frontend checks.

Avoid overly clever filters that allow cross-layer breakage.

## 7. Dependency caching

Use official GitHub Actions caches where supported:

- Python/uv cache;
- npm/pnpm cache;
- Playwright browser cache only if it materially improves runtime;
- Docker build cache in image workflows.

Never cache secret-bearing config or private benchmark data.

## 8. Artifacts

Upload useful failure/debug artifacts with bounded retention:

- test reports;
- Playwright screenshots/traces on failure;
- parser benchmark summary;
- golden diff report;
- coverage report if used;
- migration logs;
- image digests on release.

Do not upload real private PDFs.

## 9. Coverage

Coverage is a signal, not the product goal.

Suggested starting gates after enough code exists:

- backend unit/contract coverage target >= 80% for deterministic application logic;
- no global frontend percentage requirement initially;
- critical modules (state machine, citation validation, normalization) should have near-complete branch coverage.

Do not add meaningless tests merely to satisfy a percentage.

## 10. Static analysis and security

Introduce gradually:

### Python

- Ruff or equivalent lint/format;
- mypy/pyright if chosen;
- dependency vulnerability scan.

### TypeScript

- ESLint;
- TypeScript strict mode;
- dependency audit with noise-controlled policy.

### Repo

- secret scanning;
- large-file guard for accidental private PDFs/model weights;
- generated files/benchmarks ignored appropriately.

A security scanner finding should fail CI only according to a documented severity policy, not arbitrary tool noise.

## 11. Migration safety

Every DB migration PR must prove:

- migrations apply from an empty DB;
- current test fixture DB upgrades successfully;
- application starts against migrated schema;
- destructive migrations have an explicit backup/rollback strategy.

Production migrations run before switching traffic/application version when compatibility requires it.

## 12. Release gates

A release candidate cannot be promoted if any applicable gate fails:

```text
software CI green
parser golden suite green
critical-field benchmark non-regression
retrieval mini-eval non-regression
migration smoke green
production image build green
```

From Phase 7 onward also require:

```text
backup recent/verified
health smoke after deploy
rollback target known
```

## 13. Model release gates

Model artifacts are released separately from application code.

For OCR/parser model promotion require:

- model version;
- base model;
- dataset version;
- training config;
- checksum;
- frozen benchmark results;
- baseline comparison;
- explicit promotion decision.

For LLM changes require offline QA benchmark comparison before changing production default.

Do not auto-update to “latest” model tags in production.

## 14. Home worker deployment

The Windows AI node has its own version file/config.

Minimum operational behavior:

- starts automatically after reboot;
- reports worker version/model versions via `/health`;
- supports rollback to previous application/model config;
- VM tolerates older worker during controlled compatibility window or rejects incompatible versions explicitly.

## 15. Suggested status checks by phase

### Phase 0

```text
docs-check
backend-lint
backend-test
frontend-lint-typecheck-test
compose-config
```

### Phase 1 additions

```text
parser-contract-tests
parser-benchmark-smoke
```

### Phase 2 additions

```text
ingestion-integration
admin-parser-golden-tests
db-migration-test
```

### Phase 3 additions

```text
web-component-tests
web-e2e-smoke
```

### Phase 4 additions

```text
rag-unit-tests
rag-eval-mini
ai-worker-contract
```

### Phase 5 additions

```text
cross-document-retrieval
incremental-indexing
```

### Phase 6 additions

```text
feedback-dataset-tests
model-promotion-regression-tests
```

### Phase 7 additions

```text
production-image-build
deployment-smoke
```

## 16. Current repository bootstrap workflow

Until application code exists, the checked-in CI skeleton should only validate repository/document hygiene. Codex should expand `ci.yml` during Phase 0 rather than introducing jobs that fail because no Python/JS project exists yet.

That rule prevents a permanently red empty repository while still putting CI structure in place from day one.
