# Feature 107: Durable candidate execution evidence

## Status

Implemented (2026-09-16). Feature 107 adds an independent recorded-execution wrapper around
Feature 106, with a CLI for execution and read-only inspection.

## Decision and scope

`run_candidate_execution_recorded` requires a caller-selected, new `attempt_path`. It exclusively
creates that directory, durably publishes a canonical launch intent, invokes the Feature 106
runner once, then writes a canonical result and a completion descriptor. Any existing attempt
path is rejected before invoking the runner, even if it is empty or appears complete.

`inspect_candidate_execution_record` validates the retained intent/result/completion binding
against the supplied plan, admission and caller pins. Inspection is read-only. A valid intent
without a result or completion, or any temporary publication node, reports an uncertain outcome.
Malformed, unsafe or identity-inconsistent evidence produces a fixed error. Neither state permits
another runner invocation, repair, cleanup, result synthesis or automatic resume.

The directory scopes the no-replay rule. A different new directory creates another explicit
attempt. Intent records authorization to enter the runner, not proof that `Popen` or `execve`
happened. A crash after intent and before runner entry can leave zero executions while still
prohibiting another invocation for the retained attempt.

## Requirements

- FR-107-01: Reconstruct Feature 103 plan and Feature 104 admission and check optional caller pins
  before attempt mutation. Feature 106 remains responsible for its complete execution-boundary
  validation; the wrapper must not weaken or bypass any checks.
- FR-107-02: The attempt parent must be an existing physical directory; `attempt_path` must not
  exist. Reject unsafe ancestry and directory identity overlap with workspace/input roots.
  Exclusively create the attempt with mode 0700, retain its directory descriptor and recheck
  ownership. Existing directories, files, symlinks and partial attempts never authorize execution.
- FR-107-03: Before runner entry, durably publish canonical `launch-intent.json`. Bind plan,
  admission, bundle and contract digests; source/input file-table digests; workspace/input/attempt
  device/inode identities; and a fresh random nonce. Complete no-clobber creation,
  file/directory fsync and exact revalidation before calling Feature 106.
- FR-107-04: Only the caller that exclusively created and completed the first intent can invoke
  Feature 106 once. Existing intent or prior success grants no new execution authority. Concurrent
  callers to the same attempt cannot both enter the runner.
- FR-107-05: After Feature 106 returns, detach and validate its result against the same declarations.
  Persist canonical `result.json` containing `CandidateExecutionRun.to_dict()`, a canonical result
  payload digest and the exact intent digest. Successful, failed and timed-out outcomes can each
  be recorded; recording does not change process status or confer evaluator acceptance.
- FR-107-06: Publish `completed.json` only after the intent and result are synced and rechecked.
  Bind their exact canonical SHA-256, sizes and observed file device/inode identities. Sync and
  reread the complete binding before returning a completed record.
- FR-107-07: Preserve ambiguous attempts after authorization, runner exception, partial writes,
  sync failure or changed evidence. Never infer a result from candidate outputs or an unbound
  result file. No recovery path guesses a surviving PID or terminates an unknown process.
- FR-107-08: Inspection performs bounded no-follow reads and stable file/directory checks,
  validates canonical schemas and supplied declaration pins, and never modifies files. It need
  not reopen the original workspace/input trees or require their bytes to remain unchanged after
  execution. Retained identities and declaration agreement establish record consistency only.
- FR-107-09: Persistent/public JSON excludes raw stdout/stderr, absolute local paths, command
  arguments, environment values, source/input bytes, PIDs, scores and evaluator reports. Local
  path information may be exposed separately to the immediate API caller.
- FR-107-10: No home/Store initialization, evaluator/provider invocation, Candidate/receipt/archive/
  ledger event creation, materialization attestation or resume integration is included.

## Public API

```python
run_candidate_execution_recorded(
    admission,
    *,
    plan,
    workspace_path,
    input_path,
    attempt_path,
    expected_admission_sha256=None,
    expected_plan_sha256=None,
    expected_bundle_sha256=None,
    expected_contract_sha256=None,
)

inspect_candidate_execution_record(
    attempt_path,
    *,
    plan,
    admission,
    expected_admission_sha256=None,
    expected_plan_sha256=None,
    expected_bundle_sha256=None,
    expected_contract_sha256=None,
    expected_completion_sha256=None,
)
```

Both return `CandidateExecutionRecord`. Its `to_dict()` distinguishes `recorded` or `uncertain`
record completeness from the nested runner's `succeeded`/`failed`/`timed_out`. Feature 106's direct
`run_candidate_execution` retains its existing one-shot telemetry behavior.

## Errors and trust boundary

`CandidateExecutionEvidenceError` exposes `candidate_execution_evidence_` plus one of:
`invalid`, `plan_mismatch`, `admission_mismatch`, `identity_mismatch`, `root_unsafe`,
`source_changed`, `input_changed`, `attempt_exists`, `write_failed`, `record_changed`, `runner_failed`.
Messages exclude OS prose and caller-controlled contents. Unsafe evidence cannot be downgraded to
an absent attempt.

Reuse Feature 102--106 descriptor helpers and declaration validators. Do not reuse the old
materialization launch/execution modules, which bind Run/Store, parent/child/task and single-file
candidate identities and carry another recovery protocol.

The guarantee is at most one authorized Feature 106 invocation per retained attempt through this
wrapper. It is not exactly-once execution, process authenticity or resistance to consistent removal
or replacement of all evidence by a same-user actor. No-follow checks are bounded observations;
neither this wrapper nor Feature 106 is a filesystem/process sandbox.

## Non-goals

No Store, evaluator, attestation, resume or repair; no Candidate/archive/score authority; no automatic
cleanup/retry of uncertain attempts; no controller ownership integration, dependency/environment
authentication, unknown-process supervision, real framework/provider integration or performance claim.
