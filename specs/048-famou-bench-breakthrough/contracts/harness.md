# Contract: Exact Famou Harness v1

Lunar invokes the explicit harness command as:

```text
<harness-command...> <attempt>/harness/request.json
```

with `<attempt>/harness` as cwd. The request names `../subject` as the candidate workspace, a
relative `receipt.json` destination, and the exact benchmark/publication, evaluation-profile,
CaseRevision, case digest, extractor digest, and evaluator digest expected by the suite manifest.

The command owns all private extractor/evaluator material and credentials outside the subject
workspace. It writes a strict harness receipt atomically. Lunar rejects identity mismatch,
non-finite/unbounded metrics, a missing score on a completed extraction, or unsupported keys.

This adapter deliberately models the official extractor-then-evaluator boundary rather than
reimplementing case-specific scoring in Lunar.
