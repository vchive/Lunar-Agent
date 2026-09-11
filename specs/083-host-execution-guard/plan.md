# Plan: Host Execution Guard

## Design

Use a native process-owned IOPM assertion instead of a caffeinate subprocess. The create result
and CopyProperties verification provide a synchronous acquisition boundary; process ownership
avoids another long-lived helper/lifeline. Explicit release remains mandatory on ordinary exits.
Only the supported idle-system-sleep assertion is used, never deprecated PreventSystemSleep.

`host_awake.py` owns FFI and the assertion lifecycle. Its MacOSIdleSleepAssertion API is acquire(),
verify(), release(); acquire/verify return fixed assertion evidence, release is idempotent after
successful cleanup. HostAwakeError contains a fixed safe code, not native exception prose.

`host_session.py` owns a single-use host_execution(report_path) context manager and clock/journal
handling. Explicit test seams supply a guard and clock source; production never detects mocks.
The scope is entered before existing CLI execution functions, not inside runner _execute_run, so
acquisition failures cannot become native trial_boundary_failed scores. Existing normal and deep
functions and returned data retain their authority. New campaigns can use the Python API directly.

An append-only, exclusive JSONL sidecar avoids replacing a trial file. It has at most starting,
active and closed events, each bounded and fsynced; fsync the parent directory on creation before
dispatch as well. Check descriptor/path identity and regularity;
reject existing destinations, symlink components and CLI destinations inside workspaces or case
sources. CLI containment resolves aliases, including missing descendants, before journal creation,
then passes the original path to the scope to retain symlink rejection. Preserve
incomplete journals on failure. Acquisition followed by an observation failure still releases.
No exceptions, environment or callback return payload are serialized.

Existing directories are compared by device/inode, because resolving path strings alone does not
canonicalize macOS case/Unicode aliases. For roots not created yet, compare missing components
conservatively with NFD normalization and case folding under the same existing ancestor identity.
This may reject a distinct, similarly named future directory on case-sensitive storage; choose a
different report directory rather than risk writing inside a workspace once it is created.

Clock samples bracket realtime with two monotonic reads. Elapsed monotonic bounds and signed
wall-minus-monotonic bounds retain uncertainty, including wall-clock adjustments. All existing
runtime/HTTP/outer deadlines remain as implemented; this is host policy and observation only.

## Data and contracts

See data-model.md. The native assertion evidence is backend=macos_iokit,
assertion_type=PreventUserIdleSystemSleep, assertion_id=nonzero uint32, owner_pid=current PID,
level=255, verified=true. The fixed name is Lunar Agent evaluation; no task text enters OS metadata.

The journal is ancillary evidence, never a subject/harness receipt. Context entry is the only
dispatch gate. Context exit verifies the assertion where possible, attempts release, persists
closure, and raises safe host failure only if it would not replace an active work exception.

## Work split and verification

Root owns SDD, CLI integration/default compatibility, final integration and documentation.
Native assertion owner implements host_awake plus focused tests. Scope owner implements
host_session plus failure-first journal/clock/lifecycle tests. Independent reviewer checks the
combined contract and recovery behavior. Run focused suites, one full regression, Ruff, Specify,
diff checks and a bounded native smoke; no real model/provider or candidate execution.

The main-checkout 082 source-closure regression used to inspect the mutable current package and
assume it still contained38 files. It now reconstructs that feature's pinned Git blobs in a
temporary fixture and binds Git responses to the same blobs. The completeness/HTTP-helper
rejection checks remain, without running sealed live-source validation against new product code.
No historical specification, campaign helper, manifest or result is changed by this test repair.

## Constitution and alternatives

No schema migration or exception. Stdlib plus fixed OS frameworks preserves standalone use;
unsupported explicit policy fails closed. Durable local sidecar and original verifier authority
preserve II/IV. Scoped ownership, rollback and tested cleanup satisfy V/VI. A no-op fallback would
misrepresent the requested host condition. A caffeinate helper adds readiness/ownership/cleanup
without improving the selected idle-sleep policy. Replacing timeout clocks or adding retries would
mix independent product contracts and is deferred.
