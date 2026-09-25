# Feature 156 validation

## Owner identity checkpoint (2026-09-25)

The local runner now records an OS-observed process start identity in its durable registration
before gate release, repeats it in the terminal receipt, and rejects a mismatched identity before
in-process cleanup. If identity becomes unreadable, the live controller may retain cleanup authority
only after reaping its child and confirming the leader PID is absent; a reused visible PID is denied.
Darwin reads microsecond start time from `libproc`; Linux records the boot ID and `/proc` start tick.
Recovery checks the registration-to-receipt binding but remains read-only:
there is no post-crash owner-checked cleanup or terminal recovery receipt yet. T156-06 therefore
remains open, as do trusted bootstrap integration and byte-bound execution on other platforms.

The owner-identity and Feature 156/157/158 focused suites pass **133 tests**. The final code also
passes the full offline repository suite, Ruff, compileall, and diff checks. No provider, external
producer, scheduler, or campaign was run.

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

This was not yet the full acceptance matrix. Request-level timeout was a declaration to the
producer and could not be enforced inside an arbitrary executable by the parent process. A
non-cooperating executable could do work before reading the gate. At this checkpoint Darwin
used a private immutable snapshot, while Linux and other non-Darwin platforms still re-opened
the executable by pathname between the final identity check and `Popen`. The default scheduler
did not call this runner.

The descendant cleanup gap is now addressed for descendants that remain in the registered
process group. The runner cleans that group when the leader exits and retains the first cleanup
evidence; fixture tests cover inherited pipes, redirected pipes, and a descendant that ignores
SIGTERM. A descendant that leaves the registered group remains outside this ownership contract.

The macOS local probe confirmed that a shebang fixture cannot be launched through `/dev/fd` even
when the verified descriptor is inherited by the child. `fexecve` and `execveat` are unavailable
through the local Python/libc interface. Darwin now uses a private immutable executable snapshot;
the replacement-after-final-check fixture verifies that the snapshot bytes run and that a failed
immutable lock rejects before spawn. Linux uses a sealed memfd inherited across `Popen` and
executed through `/proc/self/fd`; other platforms retain the `pathname_unbound` prototype.

## Linux byte-bound launch follow-up (2026-09-25)

The Linux runner now holds a sealed memfd through `Popen` and passes it in `pass_fds` along with
the registration gate. The actual Linux fixture replaces the source path inside the `Popen`
callback, after the runner's final identity check. The original shebang script still completes,
the registration and terminal receipt bind its digest as `linux-sealed-memfd`, and the parent
descriptor is closed after process creation. An unavailable Linux binding rejects before spawn
after the one-time attestation has been consumed. The focused Linux producer-process and binding
suites passed with **46 passed, 2 skipped**; Ruff, compileall, and diff checks passed locally.
The Darwin focused suite passes with the Linux-only tests skipped. This closes the Linux pathname
replacement window, but external admission remains blocked by the trusted pre-gate bootstrap and
host-observed request enforcement; other platforms remain pathname-bound prototypes.

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

At this checkpoint T156-05, T156-06, T156-09, T156-11, T156-11b, T156-12, and T156-14 remained
open. T156-11b is now complete for Linux as recorded above. The trusted bootstrap is still
fixture-only, and controller-owned request evidence is not yet connected to the runner.
