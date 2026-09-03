# Data Model: Execution-Grounded Conversational Evolution

No SQLite migration is required.

## CandidateInputArtifact

```json
{
  "path": "data/raw/orders.csv",
  "size": 42,
  "sha256": "64 lowercase hexadecimal characters"
}
```

The source root is constructor authority and is never serialized into strategy state. Paths must be
below `data/raw/`; the runner validates source and copied bytes against size/digest.

## Search execution evidence

The existing `CandidateExecution` schema remains canonical. On success its `artifacts` contains
only present, independently validated contract output paths. Output-contract failure changes status
to `failed`, sets `error=output_contract_invalid`, and retains a bounded evaluator reason in
stderr. The archive's `EvaluationReport` then receives local validity zero.

## Runner fingerprint

`EvolutionConfig.runner_fingerprint` is SHA-256 over a canonical object containing protocol
version, Python implementation/version, contract digest, and ordered input path/size/digest tuples.
The object itself is not persisted.
