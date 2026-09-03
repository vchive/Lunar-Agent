# Contract: Frozen Evaluator Bundle

## Compiler

Input is a bounded prompt containing the canonical algorithm contract and protocol. Output is one
strict JSON compiler envelope; markdown fences, unknown fields, external commands, and paths are
rejected.

## Evaluator

Invocation is `python -I evaluator.py <candidate.py>`. The candidate has already run. Its sibling
workspace contains `execution.json`, verified `data/raw/*`, and contract-declared `output/*`.
Stdout must be exactly one canonical `EvaluationReport` JSON object. Non-zero exit, stderr-only
failure, malformed JSON, invalid schema, timeout, or oversized output is a candidate evaluation
failure.

## Probe preflight

- Lunar-Agent writes only declared synthetic files under a private probe workspace.
- Every probe receives a placeholder candidate and canonical successful execution evidence.
- Validity must match `expected_validity`.
- Each invalid constraint probe must include its exact `constraint_id` in `error_info.code`.
- Every declared `better` report must have strictly greater `combined_score` than `worse`.

## Freeze and recovery

The promoted directory contains exactly `objective.md`, `evaluator.py`, `probes.json`, and
`manifest.json`. Loader and per-candidate evaluation verify regular-file type, permissions, exact
shape, SHA-256 digests, aggregate digest, and contract digest before use.
