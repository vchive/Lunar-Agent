# Validation

## Scope of this checkpoint

2026-09-20: Phase A foreground implementation is complete. A shared monotonic deadline now spans
contract intake, preparation, generation, candidate execution, independent scoring, selection and
parent delivery. Durable orchestration prevents premature parent success. Solve, resume and answer
share execution admission; process-local ownership plus a nonblocking workspace lock excludes
concurrent foreground owners. Answer acquires ownership before accepting its artifact.

This is one **active execution** budget. Human waiting and admissible explicit continuations create
separate execution identities under the same policy. Observed exhaustion is terminal and cannot
be replenished by continuation. The status projection contains bounded recorded facts and never
reconstructs a live monotonic remainder from persisted timestamps.

Phase B in-flight cancellation, owned process registration/cleanup and Phase C detached entry
points remain open. Automatic `--detach` remains rejected. Typed cooperative stop checks and
narrower local process timeouts do not establish immediate cancellation of every running process
or termination of remote provider work.

## Offline acceptance

| Area | Evidence | Result |
| --- | --- | --- |
| Policy validation | solve/resume/answer bounds, unsupported modes, exact restoration, legacy injection rejection | Pass |
| Shared deadline | Deterministic native fixture covers contract/compiler/auditor/generation, local execution, scoring and delivery under one control | Pass |
| Immutable identity | Frozen inputs, profile, contract, evaluator and plan bytes retain their configured ceilings while actual process timeouts narrow | Pass |
| Parent lifecycle | Parent running during delivery, one reused orchestration task, ordinary scheduler exclusion, child failure cannot succeed parent | Pass |
| Recovery | Human wait starts a new active execution; valid preparation recovery retained; corrupt recovery rejected before any new observation; successful/exhausted continuation is read-only | Pass |
| Terminal precedence | One solve-policy budget event; cancellation-first and budget-first preserved; late task success cannot replace the budget failure | Pass |
| Ownership | Busy same-process and cross-process owners reject admission; busy answer does not consume input or write artifacts | Pass |
| Status | Fixed fields, absent/explicit policy origin, successful final delivery phase, malformed observation rejection and no status writes | Pass |
| Delivery | Deadline checks after material reads, before copy/output commit, and before successful parent settlement; unfinished output batches reconcile on typed stop | Pass |
| In-flight cancellation and local cleanup | Full owned probe/candidate/evaluator fan-out | Not implemented in this checkpoint |
| Detached execution | Automatic entry point remains rejected | Gate preserved; positive behavior not implemented |

## Focused verification

New/extended suites:

- `tests/test_automatic_solve_lifecycle.py`: deadline math, typed stop, process/workspace ownership,
  unsafe lock rejection, and budget failure between last-task success and parent settlement.
- `tests/test_automatic_solve_deadline_integration.py`: 15 native offline integration cases, all
  passing; local model responses are fixtures, and candidate/evaluator programs are fresh fixtures.
- `tests/test_automatic_solve_status.py`: 13 cases passing, including answer identity, read-only
  status, bounded diagnostics and terminal winner behavior.
- `tests/test_solve_budget_propagation.py`: 23 cases passing, including timeout ceilings,
  independent scoring admission and typed stops surviving broad exception handlers.
- `tests/test_automatic_solve_orchestration.py`: Store, scheduler, child outcome, delivery and legacy
  compatibility; output-publication Store tests cover rejection after failed/cancelled parents.

The policy/preparation/automatic-bundle/orchestration compatibility command passed 227 tests.
Preparation-recovery/status/deadline integration passed 42 tests before the final five boundary
cases were added. A subsequent 28-test status/integration run and independent 15-test integration
run passed. Final Store/Controller/run-budget/lifecycle/status refinement passed 46 tests. The
materialization and attestation compatibility suites passed 186 tests after the additive task
schema fixture update; publication and lifecycle boundary suites passed 134 tests.

Ruff for all `src` and `tests`, compileall, Specify prerequisites with `--require-tasks
--include-tasks`, and `git diff --check` pass. Local Markdown links are checked before commit.

## Full regression

The final two-stage run is recorded in `.lunar/test-results/feature142-final3/`:

- Current working tree: **8522 passed, 1 skipped, 24 deselected**, 0 failures and 0 errors,
  exit 0 (`current.xml`).
- Frozen Feature 123 registration stage: **24 passed**, 0 skipped, 0 failures and 0 errors,
  exit 0 (`frozen123.xml`).

The current stage executed 8523 collected tests; the 24 deselected nodes are the immutable
historical registration selection. The run took 790.25 seconds. The earlier interrupted run and
its partial report remain historical context only.

## Independent review and retained evidence

Independent budget-boundary review found and resolved typed timeout swallowing (including the
`TimeoutError`/`OSError` inheritance boundary), fresh per-stage allowances, missing scoring timeout
propagation and late publication checks. Independent lifecycle review found and resolved busy
answer consumption, incomplete status records and preparation recovery mutation before admission.
The task discriminator schema refinement and cross-process advisory owner are documented in the
existing SDD; this is a continuation of Feature 142.

Feature 131 retained inventory: **21 files / 155485 bytes**. Feature 134: **97 files / 327394 bytes**.
Each relative path, size and SHA-256 matches its retained `postrun/evidence.json`; no symlinks or
historical SQLite mutation. The product diff contains no Feature 139 source/evidence change.
No provider, real campaign, retained generated program, or WebAgent was executed.

## Release boundary

Offline correctness here does not establish evaluator quality, current-model task success,
WebAgent parity or successful real automatic multi-file delivery. Feature 139 remains preparation
1/1 and primary/joint 0/1. Phase B/C and a separately scoped real acceptance remain outstanding;
this checkpoint does not claim the whole feature or system release is complete.
