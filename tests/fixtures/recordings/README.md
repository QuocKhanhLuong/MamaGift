# Synthetic contract recordings — NOT benchmark evidence

These files are hand-authored `ProviderParseResult` payloads written in each provider's
own output vocabulary. They exist for one reason: to prove that every parser adapter
normalizes into a valid `CanonicalDocument` with intact page/block provenance on a
CPU-only CI runner, without installing multi-GB parsers.

They say **nothing** about how MinerU, Marker, Docling or PP-StructureV3 actually
perform on Vietnamese administrative documents. No benchmark number may be derived
from them, and no benchmark manifest may point at them. Every payload carries
`provider_artifact.not_benchmark_evidence: true` so a misuse is visible in the output.

Recordings captured from **real** provider runs belong in
`benchmarks/parser/recordings/` instead.

Regenerate with:

```bash
uv run python tests/fixtures/generate_recordings.py
```
