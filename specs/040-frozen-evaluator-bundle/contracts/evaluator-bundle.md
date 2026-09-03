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

Feature 040 originally promoted `objective.md`, `evaluator.py`, `probes.json`, and `manifest.json`.
Features 041–042 extend the current `frozen-evaluator-bundle-v2` file set with canonical
`input-profile.json` and independent `audit.json`. Loader and per-candidate evaluation verify
regular-file type, permissions, exact shape, canonical suite/profile bytes, SHA-256 digests,
aggregate digest, and contract digest before use.

Bundles created with protocol `frozen-evaluator-bundle-v1` are intentionally not migrated in
place. A v2 loader fails closed on them; rerun compilation with the original contract and private
inputs to create fresh compiler and adversarial-audit evidence.
