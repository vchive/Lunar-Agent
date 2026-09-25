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

The focused matrix must include: successful gated completion; a hostile pre-gate side-effect
fixture; child exit before gate/broken gate delivery; nonce replay; tuple and executable
identity drift; shell/credential rejection; registration write failure;
full stdout/stderr pipes; deterministic output overflow; wall timeout; PID/PGID ownership loss;
SIGTERM/SIGKILL uncertainty; controller interruption; symlinked/replaced/truncated envelope;
unstable receipt writes; recovery with no automatic relaunch; and a replacement exactly between
the final executable check and process creation that cannot execute un-attested bytes.

## Implementation checkpoint (2026-09-24)

The local runner now claims the nonce once across the workspace, revalidates launch identity,
starts a cooperating fixture without a shell and with a fixed non-secret environment, records
PID/PGID before gate release, bounds stdout/stderr and wall time, verifies the result file through
a held no-follow directory descriptor, and atomically publishes a chained terminal receipt.
Recovery verifies the claim, registration, and terminal receipt without relaunching. The focused
provider-free matrix covers gate order, cross-batch nonce replay, executable drift, nonzero exit,
request and output limits, timeout, envelope/directory replacement, registration/terminal write
failures, duplicate JSON keys, and recovery tampering. The focused matrix has **31 passing tests**.
The final offline repository regression has **7345 passed, 1 skipped**; Ruff, compileall, and
`git diff --check` pass.

This is not yet the full acceptance matrix. Request-level timeout is a declaration to the producer
and cannot be enforced inside an arbitrary executable by the parent process; the protocol needs
an acknowledged request-level receipt or a controlled producer SDK. A non-cooperating executable
can do work before reading the gate, so gate participation needs an explicit trusted producer
contract before this runner is connected to an external campaign. Darwin uses a private immutable
snapshot of the verified executable bytes. On non-Darwin platforms the executable is still
re-opened by pathname between its final identity check and `Popen`, so a concurrent replacement
can run bytes that were not attested. That platform gap remains a release blocker for external
producer admission, along with the cooperative gate and request-level evidence. The default
scheduler does not call this runner.

The descendant cleanup gap is now addressed for descendants that remain in the registered
process group. The runner cleans that group when the leader exits and retains the first cleanup
evidence; fixture tests cover inherited pipes, redirected pipes, and a descendant that ignores
SIGTERM. A descendant that leaves the registered group remains outside this ownership contract.

The macOS local probe confirmed that a shebang fixture cannot be launched through `/dev/fd` even
when the verified descriptor is inherited by the child. `fexecve` and `execveat` are unavailable
through the local Python/libc interface. Darwin now uses a private immutable executable snapshot;
the replacement-after-final-check fixture verifies that the snapshot bytes run and that a failed
immutable lock rejects before spawn. Non-Darwin remains `pathname_unbound` until a
descriptor-bound mechanism is specified and tested, so it is not external-admission ready.

## Deadline and fault-injection follow-up (2026-09-24)

The cleanup primitive now accepts one absolute monotonic deadline. SIGTERM grace, SIGKILL
grace, and the final leader wait are all clipped to that deadline; a post-deadline live group
is reported as `cleanup_unverified` rather than extending the attempt. The trusted bootstrap
fixture passes that same deadline through both normal and exceptional cleanup paths.

The capture evidence path retains and hashes exactly the in-budget prefix when one non-blocking
read crosses the stream ceiling; the receipt still records a saturated `limit + 1` observation
and `truncated=true`. Process waits use a zero-clamped remaining timeout, so an exhausted wall
deadline cannot add an extra wait interval.

The focused process-ownership, producer-process, and trusted-bootstrap-runtime suites pass.
New fixtures cover capture-read failure, SIGTERM failure, SIGKILL failure, cleanup uncertainty
projection, owner-loss without a direct fallback kill, child exit after registration but before
gate release, broken gate delivery, and a two-phase cleanup that cannot exceed the absolute
deadline. T156-13 is complete; T156-09's broader lifecycle matrix remains open.

T156-05, T156-06, T156-09, T156-11, T156-11b, T156-12, and T156-14 remain open:
request-level timeout is still cooperative, non-Darwin execution is pathname-bound, trusted
bootstrap is fixture-only, and controller-owned request evidence is not yet connected.
