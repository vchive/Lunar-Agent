# Feature 116 validation

Product changes: question-aware input lookup/answer/settlement/scheduling, durable automatic
preparation observations, typed evaluator runtime failures and CLI/status projection. No schema
migration, runtime fingerprint change, evaluator manifest change or new dependency.

## Focused checks

Seven-file regression: **160 passed in 47.02s**, covering the new Store, preparation and CLI
recovery tests plus existing automatic solve and frozen/snapshot evaluator paths.
Log: `/private/tmp/lunar116-focused.log`.

After the final continuation-guard fix, independent review ran all **69 new tests successfully**:
13 question-waiting tests, 43 preparation/recovery tests and 13 public CLI recovery tests. Final
review reports no remaining blocker. An independent local reproduction confirms that cancellation
or budget failure during a normal compiler response yields compiler=1/auditor=0, no frozen bundle
or profile and a nonrecoverable observation.

The independent Store work also ran 644 relevant Store/controller/interactive/plan and
publication/materialization regressions. New tests cover null/empty/Unicode-blank questions,
real clarification behind earlier dependency waits, no stray-answer artifact or dependency
release, compiler/auditor runtime failures, safe event categories, retained contract bytes,
read-only status, explicit same-run recovery, old false awaiting_input correction on continuation,
cancellation/drift, unknown interruption, observation-write failure and terminal idempotency.

## Final checks

Independent review found that a parent becoming terminal during compiler execution could still
start the auditor or publish preparation. The initial broad run was intentionally interrupted
after 1901 passed / 1 skipped to address this; it is not the final validation. The final regression
below ran after the added inter-stage continuation checks were frozen.
Interrupted log: `/private/tmp/lunar116-interrupted.log`.

Final full regression: **5636 passed, 1 skipped in 383.95s**. JUnit records 5637 tests, zero
failures/errors and the existing filesystem case-alias skip. Logs:
`/private/tmp/lunar116-full.log` and `/private/tmp/lunar116-full.xml`. No product or test changes
followed this full run.
Ruff over all source/tests, compileall, installed CLI help, Specify prerequisites and diff checks
passed. Existing Feature 112 subprocess quickstart passed: scores 1, 2, 6, 7, one delivery and
unchanged contract/compiler/auditor/Agent/candidate counts 1/1/1/4/4 after terminal resume.
Log: `/private/tmp/lunar116-quickstart.log`.
All 111 local documentation links checked in the updated documentation/spec set resolve.
Verified work is committed and pushed to `origin/main` under the user's standing instruction.

## Scope and limits

No provider requests were made. Feature 113 and 115 measurement source, tests, registration and
postrun results are unchanged against `f9010c5` / `4d0acdc`; older frozen directories are unchanged
against `027a235`. They still report separate 0/2 outcomes and are not reopened.

An unmatched start is unknown and may represent ongoing work or interruption. This feature does
not add provider reconciliation, usage accounting, automatic retries, a whole-run deadline or
active-process cancellation orchestration. Recoverable is a permission to try explicitly after
validation, not a prediction of success. Invalid pre-preparation evidence retains the existing
rejection path without an attempt; historical runs without observations gain no invented failure
record. Read-only status does not rewrite historical parent states.
