# Host observation contract

Journal v1 uses bounded JSON lines with kind=host_execution, a generated session UUID, owner_pid,
policy=prevent_idle_system_sleep and increasing sequence. Lifecycle events are starting, active,
closed. Starting is durable before acquisition; active includes verified assertion evidence and
is durable before the with-body. Closed distinguishes work outcome from guard verification,
release and journal outcomes. Missing/partial closed events do not establish cleanup.

`schema_version` is the string `"1"`. Each event is at most 8192 bytes including its newline;
the scope appends at most three events and creates the file with mode0600. An incomplete write
may leave a partial line; no attempt repairs or replaces it.

| Field | Fixed values and meaning |
| --- | --- |
| acquisition_outcome | not_attempted, attempting, acquired, failed; acquired requires validated evidence |
| verification_outcome | not_attempted, verified, failed; closed records the exit check when applicable |
| release_outcome | not_attempted, returned, failed; returned means release() returned, including prior rollback or no-op cleanup |
| work_outcome | not_started, returned, raised; independent of native result validity |
| clock_outcome | observed, failed; failed end sample and elapsed projection are null |
| journal_outcome | append_requested; a record cannot attest its own completed fsync |

Each sample records wall_time_ns, monotonic_before_ns and monotonic_after_ns. Clock info records
implementation, adjustable, monotonic and resolution; no hostname or full platform inventory.
Final elapsed projection includes signed wall elapsed and monotonic lower/upper elapsed bounds;
signed clock-divergence bounds are descriptive, not sleep_seconds. Invalid/nonfinite/type-invalid
clock samples cannot be silently repaired. Wall adjustments are permitted and remain signed.
Elapsed bounds cover the observation interval from before acquisition to after release, including
scope overhead; they are neither protected-body timings nor individual model-request timings.

Assertion evidence records the fixed backend/type, nonzero uint32 assertion ID, current owner PID,
level255 and verified=true. No scores, native receipt fields, request content, secrets, command
arguments, exception prose or callback data are stored. Native result schemas are unchanged.

CLI host journals live outside the protected trial workspace and all case-source roots. They are
never overwritten or reused on resume: each invocation supplies a fresh path and its own assertion.
File and initial directory fsync are dispatch prerequisites. A readable closed line records the
closure observation and its append attempt; it cannot prove that its own final fsync succeeded.
The caller's successful scope exit is needed to establish that all persistence calls returned.

Scope entry/exit claims are serialized within one process. Cross-PID entry or exit rejects before
touching the parent's assertion or journal, even if a child supplies a work exception. Preserving
the original work exception applies to exits by the owning process. Failed descriptor closure is
reported as uncertain cleanup; a close attempt never retries a potentially reused descriptor ID.
