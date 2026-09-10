# Plan: Master Planning Role Fixed Measurement

## Design decisions

Use the 076 wrapper pattern and native `EffectTrialRunner`/exact harness seam through small,
explicit direct bindings to the pinned 074 helper engine, without another loader layer. Change only
registration metadata, slot preparation and postrun projections;
do not fork the subject adapter or copy evaluator logic. The manifest must pin the integrated 077
source `fba6ab8cf5b27d3bd1b42f353907a6ae21c25ef9`, every new script/test/input byte and the complete
23-file helper closure before launch. Historical context pins Feature 076's sealed chain, including
its inherited history, without putting any historical attempt into the new denominator.

Keep the protocol deliberately matched to 076. Reusing its cases, model, budgets and wave makes
the observed stage counts comparable as context, while the two campaigns remain independent
denominators. The comparison is descriptive only because attempts are not paired controls and
provider conditions can differ.

## Execution sequence

1. Write the registration, source/input/helper inventory and acceptance rules; run an independent
   preaudit and guarded dry-run with provider access blocked.
2. Commit and push the registration before any start marker. Verify that both slot workspaces are
   fresh, exclusive and free of result artifacts.
3. Launch exactly once and observe both slots through terminal state. Use read-only progress polling;
   do not run a second launch or repair a failed slot.
4. After termination, run the independent final audit, native summary reconciliation and scoped
   process check. Render a report that keeps unresolved fields `null` and records visibility limits.
5. Re-read the evidence hashes and update the SDD task status and `HANDOFF.md` only after sealing.

## Required report fields

Per slot: case/arm identity, subject process state, Master plan accepted, Build entered, checkpoint
and resume flags, candidate metadata-only observations, subject receipt state, harness/evaluator
state, validity, quality/overall scores, bounded diagnostic projection, terminal outcome and SHA
links. Aggregate: fixed planned=2 from registration, started/terminal/unresolved counts,
plan/Build evidence, observed valid-solution count/rate, scored-valid sample count, and explicit
unknown usage/cost/duration fields. Partial observations retain the fixed denominator but cannot be
described as final failure rates.

## Failure handling

An unstarted or interrupted slot is unresolved until its durable terminal marker is independently
verified. A failed slot is retained as observed and never replaced. Candidate files are inspected
only for metadata and are never executed or sent to the harness after subject failure. Any source,
manifest, input or helper drift aborts prelaunch without attempting a model call.

## Inherited data and contracts

Reuse the native score-free subject request/receipt, immutable attempt record, exact harness receipt,
workflow manifest/policy, public-file ledger and accepted summary schemas. The current wrappers own
only their campaign/source/path identity, independent freeze set, historical anchors and report
heading. Master=1200, Build=2400, reserve=120 and checkpoint_after_rounds=32 remain fixed, sharing the
5400-second/200-tool/8,000,000-token ledger. Unknown complete failure usage/cost, exact Master duration
and scores remain null. No new product persistent fields or recovery authority are introduced.

## Runnable offline quickstart

Run from the isolated worktree, with the main development virtualenv and explicit isolated imports:

```sh
PYTHONPATH="$PWD/src" /Users/liminghan/Documents/lunar_agent/.venv/bin/python -c 'from pathlib import Path; import famou.staged_workflow as m; assert Path(m.__file__).resolve() == Path("src/famou/staged_workflow.py").resolve(); print(m.__file__)'
PYTHONPATH="$PWD/src" /Users/liminghan/Documents/lunar_agent/.venv/bin/python -m pytest -o addopts='' -q tests/test_measurement078_audit.py tests/test_measurement078_runner.py specs/078-master-planning-role-measurement/postrun/test_audit.py tests/test_master_planning_role_integration.py
/Users/liminghan/Documents/lunar_agent/.venv/bin/ruff check specs/078-master-planning-role-measurement tests/test_measurement078_audit.py tests/test_measurement078_runner.py
bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```

These commands use synthetic local fixtures and do not prepare a real registration or call a
provider. Root owns actual materialization, independent preaudit/dry-run and unique dispatch only
after review and integration. Before dispatch, actual public/private/harness bytes and installed
dependency versions must be checked, and registration/reports must be committed and pushed.

## Constitution review and migration

No exception. Independent native receipt/harness authority satisfies IV; the existing confined paths,
secret and shared-budget controls preserve V. Guarded registration, dispatch and failure fixtures
satisfy VI with no new product behavior. No migration or restart path is added; the new identity
cannot reopen, recover or score an old attempt. Existing native transcripts remain native artifacts,
and this measurement creates no new raw content projection.

## Deferred work

Provider-failure subtype telemetry (for example transport versus malformed response) is intentionally
out of scope. If still needed after this measurement, specify it as a separate feature with its own
offline contract and a new registration; do not alter this campaign after launch.
