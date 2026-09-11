# Feature 083: Audited Host Execution Scope

**Status**: Complete. Validation and limits are recorded in `validation/results.md`.

## Problem and goal

The sealed082 campaign observed macOS sleep/wake events and Python monotonic clocks that exclude
system sleep. Its UTC ETA was therefore invalid. Both staged attempts failed before a native
receipt; power events do not establish either model failure's cause. Future measurements need an
explicit host idle-sleep policy and separately recorded clock observations before model dispatch.

Provide an opt-in execution scope for a macOS supervisor: establish and synchronously verify an
OS-owned PreventUserIdleSystemSleep assertion, durably record that fact, run the existing operation,
then verify/release and record closure. Existing execution defaults, native results, budgets,
receipts and scoring stay unchanged. This feature does not launch another real evaluation.

## Acceptance

1. Reusable `host_execution(report_path)` context manager is separate from EffectTrialRunner.
   Normal/deep trial CLI commands expose `--keep-awake-report PATH`; absence preserves the exact
   old path, payload and process behavior. Read-only preflight does not acquire assertions.
2. On supported macOS, use fixed absolute system-framework paths and stdlib ctypes, no executable
   helper, external package, credential access or permanent power setting. Create the assertion at
   level255, require a valid nonzero uint32 ID and verify its current type/level with CopyProperties.
   Unsupported hosts and failed/unverifiable acquisition reject before executing protected work.
3. All CF functions have explicit FFI signatures and ownership handling. Roll back partial
   acquisition. Release only the current process's owned assertion; reject cross-PID use and
   repeated acquisition. Release is idempotent after successful cleanup. Do not rely on __del__.
4. The scope is single-use and creates a fresh bounded JSONL journal before acquisition. Refuse
   existing destinations, symlinks and non-regular files; do not overwrite foreign artifacts.
   Durably append starting, active and closed observations, verifying file identity and syncing
   the parent directory when the journal is created. A failed
   initial/active write prevents protected work. Partial journals after a crash are incomplete,
   never proof of release or successful work. No background thread or file writer survives scope.
5. Once acquisition was attempted, all exits attempt release, including failed active persistence,
   operation exceptions and BaseException cancellation. Preserve the original operation exception
   object if cleanup/reporting also fails. If no operation exception exists, cleanup or journal
   failure is a host-scope error; it never rewrites an existing native result or receipt.
6. Fixed observation fields describe session UUID, owner PID, assertion type/ID/level, lifecycle,
   verification and release outcomes, and work outcome (not_started/returned/raised). Do not save
   command lines, environment, exception text, prompts, candidate content or operation results.
   A returned operation may itself report failure; host closure is not evaluator success.
7. Record exact realtime ns bracketed by monotonic-before/after ns, with clock implementation,
   adjustability and resolution. Preserve raw samples and signed wall/monotonic differences;
   bracket-derived elapsed bounds must not become exact sleep duration or model-request timing.
   Wall rollback/forward adjustments remain observations. Invalid clocks are explicit failures.
   Do not change any existing timeout clock or model ledger semantics.
8. The sidecar must be outside the trial workspace and all case-source roots on CLI entry,
   including resume. Resolve aliases and missing-path ancestors for this validation before any
   journal write, while preserving the original path for the scope's symlink rejection. It cannot
   interfere with frozen workspace or public-source identity or artifact acceptance. Future wrappers
   may use the same Python scope before credential loading/dispatch; never patch sealed helpers.
9. Failure-first offline coverage includes acquisition/query/FFI failures, rollback, cancellation,
   normal and exceptional cleanup, release/report failure, single-use/PID checks, bounded safe
   journals, clock jumps, zero dispatch on failed entry, exact default compatibility and normal/
   deep CLI integration. A short local macOS smoke may acquire/query/release a real assertion and
   check process-exit cleanup without model, network, candidate or actual system-sleep execution.

## Limits

PreventUserIdleSystemSleep permits display sleep; it does not prevent lid-close, explicit sleep,
low-battery sleep or establish effectiveness during Dark Wake. Successful property checks are
point-in-time assertion evidence, not proof of uninterrupted wakefulness. An OS-managed assertion
belongs to the supervisor; its fatal exit is not a durable journal closure. Any observed OS cleanup
must be labelled as local evidence, not a cross-platform guarantee. Other platforms reject explicit
required guard requests; default execution stays available.

No model retry, request-budget change, new campaign, provider probe, WebAgent execution or company
platform query belongs here. Preserve074/076/078/082 Git seals byte for byte; never run old
live-source audits against changed product source. Staged valid0/2 and unknown scores/cost remain.
