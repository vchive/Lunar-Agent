# Plan

Use the existing task question field to distinguish input waits from dependency waits. Keep
RunStatus/TaskStatus and the SQLite schema unchanged; old rows with null questions immediately
benefit from the corrected queries. Reuse ordinary settlement on explicit continuation.

Add advisory preparation observations to the existing event ledger under the existing profile
lock. Keep `bundle_profile_prepared` and all frozen bytes as the preparation authority; diagnostic
events cannot bypass validation or authorize reconstruction. Record no provider prose. Expose a
structured preparation substatus rather than introducing a new persistent run enum or declaring
the accepted contract permanently failed. Persistence failures must not be silently suppressed.

Use a narrow typed failure classification for runtime compilation/auditing where necessary;
do not infer retryability from arbitrary strings. An unfinished start is an interrupted/unknown
observation, not a successful preparation or evidence that a provider consumed zero tokens.
Explicit resume re-enters existing validation and performs at most one preparation attempt.

Alternatives rejected: treating every WAITING as user input, permanently failing the parent on a
transient compiler error, retrying automatically, or rebuilding conflicting frozen evidence.
No new dependencies, migrations, attestation or measurement policy. No constitution exception.

Validation: focused Store/interactive and preparation/CLI recovery tests; full regression after
product freeze; existing Feature 112 subprocess quickstart; Ruff, compileall, Specify and frozen
history checks. Runnable commands are in quickstart.md.

## Data and CLI contract

Observation payloads contain `schema_version="1"`, `parent_run_id`, a random `attempt_id`,
`status`, `stage`, `error_category` and boolean `recoverable`. Start and failure events share an
attempt ID; the existing prepared event is unchanged and supplies verified success with a null
attempt ID in projections. A runtime-boundary exception has a typed compiler/auditor stage, not a
string-parsed provider message. Other preparation errors use a fixed validation category.

Read-only status normalizes the projection, checks the current parent and existing evidence, and
suppresses recovery indications after cancellation, terminal failure/success or evidence drift.
An unfinished start returns unknown/interrupted even if another process is currently preparing;
the ledger alone is not a liveness oracle. The existing lock still rejects concurrent preparation.
Recoverable means an explicit attempt may be made, not that the same provider settings must work.

`solve`/`resume`/`answer` expose `evolution.preparation`; known failures return exit 1 with parent
identity, effective `status="failed"` and unchanged durable `run_status` (normally `running`).
Status JSON keeps its existing `run.status` and places diagnostics in `evolution.preparation`.
Plain status prints preparation status, category and a resume hint when applicable. Invalid input
or frozen evidence detected before preparation retains the existing exit-2 rejection and no new
attempt. Unknown or malformed diagnostic rows never grant reuse or trigger model work.

Automatic preparation supplies an optional continuation guard to evaluator compilation. It
checks the parent at runtime stage boundaries and before publication; standalone compiler calls
retain their default behavior. This prevents an observed terminal parent from launching a later
phase. It does not interrupt an already active HTTP request or make SQLite cancellation and
filesystem publication one atomic operation. Material already frozen at a later interruption is
retained and revalidated, never regenerated merely because the preparation was incomplete.
