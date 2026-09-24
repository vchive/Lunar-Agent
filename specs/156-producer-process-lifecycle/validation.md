# Feature 156 validation

Validation is provider-free and uses short local fixture executables only. No external producer,
provider, evaluator, WebAgent, or campaign is started.

| Area | Required evidence |
| --- | --- |
| Attestation consume-once | Exact tuple, intent digest, executable bytes/size/inode/timestamps, schema, nonce, and self-digest are required. Replay, duplicate claim, altered claim, and uncertain claim state fail before spawn. |
| Process creation | `Popen` receives an argument vector, `shell=False`, `start_new_session=True`, `close_fds=True`, closed stdin, derived cwd, and no credentials or shell control text. |
| Registration gate | Child cannot perform work before a durable registration receipt records exact PID/PGID, owner identity, intent, attestation, and executable evidence. Gate or registration failure is never treated as successful execution. |
| Deadline and budgets | One monotonic deadline covers gate, process wait, pipe drain, cleanup, and envelope read. Request count, output bytes, and wall time remain independent and cannot be reset by retry or recovery. |
| Capture | Concurrent stdout/stderr draining handles full pipes without deadlock; each stream is bounded and records only byte count, digest, and truncation/status. |
| Cleanup | SIGTERM/SIGKILL is preceded by exact owner checks and uses existing process-group cleanup. Reused PID/PGID, failed liveness, callback failure, or unverified cleanup yields terminal unknown/recovery-required evidence. |
| Envelope evidence | No-follow ancestor/file checks, regular single-link requirement, size bound, before/after identity, stable bytes, and canonical digest are all verified. Replacement, symlink, truncation, append, parse, or read uncertainty is rejected or unknown according to observability. |
| Durable receipts | Every bounded receipt is fsynced and atomically committed; previous receipt digests prevent overwrite. A controller interruption leaves an inspectable terminal or recovery-required record. |
| Recovery | Recovery inspects and may clean only the exact registered group. It cannot consume another nonce, widen budgets, alter intent, reinterpret output, or relaunch. |
| Regression | Focused lifecycle tests, Ruff, compileall, diff checks, and the full project offline suite pass. Existing automatic solve and scheduler defaults remain unchanged. |

The focused matrix must include: successful gated completion; nonce replay; tuple and executable
identity drift; shell/credential rejection; child exits before gate; registration write failure;
full stdout/stderr pipes; deterministic output overflow; wall timeout; PID/PGID ownership loss;
SIGTERM/SIGKILL uncertainty; controller interruption; symlinked/replaced/truncated envelope;
unstable receipt writes; and recovery with no automatic relaunch.

## Implementation checkpoint (2026-09-24)

The local runner now claims the nonce once across the workspace, revalidates launch identity,
starts a cooperating fixture without a shell and with a fixed non-secret environment, records
PID/PGID before gate release, bounds stdout/stderr and wall time, verifies the result file through
a held no-follow directory descriptor, and atomically publishes a chained terminal receipt.
Recovery verifies the claim, registration, and terminal receipt without relaunching. The focused
provider-free matrix covers gate order, cross-batch nonce replay, executable drift, nonzero exit,
request and output limits, timeout, envelope/directory replacement, registration/terminal write
failures, duplicate JSON keys, and recovery tampering. The focused matrix has **26 passing tests**.
The final offline repository regression has **7329 passed, 1 skipped**; Ruff, compileall, and
`git diff --check` pass.

This is not yet the full acceptance matrix. Request-level timeout is a declaration to the producer
and cannot be enforced inside an arbitrary executable by the parent process; the protocol needs
an acknowledged request-level receipt or a controlled producer SDK. A non-cooperating executable
can do work before reading the gate, so gate participation needs an explicit trusted producer
contract before this runner is connected to an external campaign. Fault injection for capture
errors and signal uncertainty remains to be added. The executable is still re-opened by pathname
between its final identity check and `Popen`, so a concurrent replacement can run bytes that were
not attested. A leader that exits while a descendant retains the process group can also leave
cleanup unverified. Those are release blockers for external producer admission, along with the
cooperative gate and request-level evidence. The default scheduler does not call this runner.
