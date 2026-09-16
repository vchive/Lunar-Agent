# Feature 111 validation

Date: 2026-09-16. Validation uses local deterministic workers and real local candidate/evaluator
processes. No real model, external framework, WebAgent run or effectiveness campaign is started.

## Acceptance evidence

- The standalone subprocess quickstart compiles one goal, generates four complete two-file
  proposals, independently scores `1, 2, 6, 7`, and publishes the selected output and portable
  package into the parent task. Ordinary `deliver` and `status` expose the result. Terminal
  `solve --resume` deliberately omits `--evolve`; compiler/Agent/candidate calls stay `1 / 4 / 4`
  and the portable copy count stays `1`. Log: `/private/tmp/lunar111-quickstart.log`.
- Profile helper tests verify exact complete input ledgers, identical duplicate rows, stale/extra/
  conflicting rows, original-versus-parent input authority, semantic profile identity, retained
  snapshot byte checks, symlinks, and input-free tasks with no pre-existing data/workspace directory.
- Conversational integration covers normal intake and clarification, native bundle generation,
  independent rejection of infeasible score claims, parent outputs, terminal solve/resume,
  matching profile before answer/input mutation, child links/directories and legacy compatibility.
- Parent delivery tests verify complete package indexing, unchanged candidate invocation counts,
  selected evidence/input/output drift, reciprocal links, budgets, cancellation before delivery,
  interrupted copies/registration/terminal events, committed publication and confirmed rollback.

## Verification status

Focused new suites passed: **40** profile/input cases, **27** conversational CLI cases and **23**
parent delivery cases (**90** new cases total). Existing conversational/evolution CLI coverage
passed **79** cases, and existing bundle controller/materialization/output publication coverage
passed **158** cases. Independent review found no remaining blocking issue.

After product freeze, the complete suite passed: **5277 passed, 1 skipped in 316.71s**. JUnit
confirms 5278 tests, zero failures and zero errors, including all 90 new cases. The existing
case-alias test skips on this case-sensitive filesystem. Logs: `/private/tmp/lunar111-full.log`
and `/private/tmp/lunar111-full.xml`. No product or test changes followed this run.

The standalone quickstart was rerun after product freeze and passed. All-src/tests Ruff, compileall,
installed CLI help, Specify prerequisites, 98 local document links and `git diff --check` passed.
Frozen `specs/051*`, `074*`, `076*`, `078*` and `082*` have no changes relative to `027a235`.
The completed increment is committed and pushed to `origin/main` under the user's instruction.

## Scope

Explicit profile resources remain necessary for continuation. The existing bundle evaluation
protocol requires at least one output declaration. Source plus report can still be delivered when
all declared outputs are optional and the evaluator accepts their absence. Parent published outputs
retain the 256 KiB per-file cap; the full copied package counts toward the parent's artifact budget.
Interrupted copies without a prepared event remain non-authoritative and may be retained alongside
the eventual completed copy. A pinned prepared copy and terminal delivery are reused on replay.

Evaluator preparation, active-process cancellation orchestration, detached bundle solve, external
bundle seed imports and current-version real-model effectiveness remain separate work. Output
snapshots are evaluation-time observations; local identity checks do not authenticate host packages
or provide an OS sandbox. No new user attestation flow is introduced.
