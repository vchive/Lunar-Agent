# Contract: Private Input Profile

## Producer

The repository profiler reads only digest-verified staged input artifacts paired with canonical
contract input specs.

## Consumer

The evaluator-bundle compiler runtime receives canonical JSON appended to the immutable contract.
The profile informs parsing and validation logic but does not authorize changing contract semantics.

## Guarantees

- Paths are run-relative below `data/raw/` and carry size/SHA-256.
- CSV/JSON/JSONL fields contain only name, conservative type, null count, and unique count.
- Text contains only size and line count.
- No raw values, samples, local source paths, or credential-like content enters the profile.
- The profile is deterministic for the same bytes and contract, frozen with the evaluator, and
  verified on resume.

## Failure contract

Unsupported formats, malformed content, invalid UTF-8, duplicate fields, non-object records,
excessive bounds, path/symlink violations, or descriptor mismatch raise a bounded local error before
evaluator compilation or search begins.
