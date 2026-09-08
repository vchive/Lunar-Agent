# Plan: Bounded Subject Failure Diagnostics

1. Reproduce the actual missing-diagnostic behavior with deterministic subject fixtures before
   implementation; cover immutable public input, model failure, step exhaustion and runner loss.
2. Add a small shared strict diagnostic schema and safe bounded read/atomic publication helpers.
3. Emit the diagnostic from the built-in subject, using only bounded counters and safe typed
   classifications, preserving the original error and existing successful receipt behavior.
4. Collect diagnostics at the existing normal/deep `_invoke` boundary using pre-call request
   identity; keep all score, resume and process error behavior unchanged.
5. Clarify both prompts' entire-tree write prohibition and verify it without changing scoring.
6. Exercise hostile files and redaction cases, review compatibility, update documentation, and
   run repository quality gates. Retry real evaluation using the user's selected weaker model
   only after local verification and model connection checks.

## Decisions and alternatives

Keep stdout/stderr discarded. Persisting raw logs or exception strings would retain arbitrary
provider/tool content and possibly credentials. Use a separate sidecar instead of extending the
success receipt or logical record: diagnostics are optional claims and cannot affect scoring or
resume authority. Capture identity before invoking the child because a failed subject can alter
its request. A preexisting sidecar is stale evidence and is not collected for a new invocation.

## Data model and contract

The diagnostic contains exactly `schema_version`, `kind`, `mode`, `request_sha256`, `run_index`,
`round_index`, `stage`, `code`, `model_turns`, `tool_steps`, and `http_status`. Version is `1`, kind
is `subject_failure`, normal round is null, and deep round is a bounded positive integer. Model
turns and tool steps count observed events only; they are not a complete usage or billing ledger.
Readers enforce the 4096-byte limit before JSON parsing and use directory descriptors with
nofollow/nonblocking file opens. Publication refuses existing destinations. Read/write failures
preserve the original execution failure.

The built-in subject uses `receipt.failure.json` or `receipts/001.failure.json`. Runner collection
uses `diagnostics/subject-failure.json` or `diagnostics/subject-001-failure.json` under the attempt.
Existing requests, successful receipts, records, and resume state require no migration. External
subjects without diagnostics retain their existing `process_*` failure behavior.

## Runnable local verification

```bash
uv run pytest -o addopts='' -q tests/test_subject_diagnostics.py tests/test_effect_adapters.py \
  tests/test_effect_trial.py tests/test_deep_effect_trial.py
uv run ruff check src tests
```

These fixtures execute the normal/deep subject and runner boundaries with deterministic runtime
failures, including a second-round failure after a scored round, without provider credentials.
The machine-local GLM evaluation then uses the existing subject and exact private harness adapters;
it is a standalone case score because no matching GLM per-run baseline exists in the frozen kit.

## Complexity tracking

No new dependency, process log format, service, or resume authority is introduced. CC Switch is an
explicitly authorized local experiment configuration source, not a product runtime dependency.
