# Validation

## Scope of this checkpoint

2026-09-20: Phase A foreground implementation and Phase B cancellation/process cleanup are
complete. A shared monotonic deadline now spans
contract intake, preparation, generation, candidate execution, independent scoring, selection and
parent delivery. Durable orchestration prevents premature parent success. Solve, resume and answer
share execution admission; process-local ownership plus a nonblocking workspace lock excludes
concurrent foreground owners. Answer acquires ownership before accepting its artifact.

This is one **active execution** budget. Human waiting and admissible explicit continuations create
separate execution identities under the same policy. Observed exhaustion is terminal and cannot
be replenished by continuation. The status projection contains bounded recorded facts and never
reconstructs a live monotonic remainder from persisted timestamps.

Phase B in-flight cancellation and owned process registration/cleanup are verified. Parent
cancellation selects only an exactly verified linked child; probe, candidate and evaluator
processes register their PID/PGID and release ownership, while cancellation and deadline cleanup
fan out through owned groups before the coordinating worker. Failed cleanup retains the durable
registration and blocks replacement work. Phase C detached entry points remain open and automatic
`--detach` remains rejected. Local cleanup does not terminate remote provider work.

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
| In-flight cancellation and local cleanup | Verified parent/child fan-out, probe/candidate/evaluator PID/PGID registration, ownership release, cancellation/deadline races, late-response guards, cleanup failure retention, and cleanup ordering | Pass (local fixtures) |
| Detached execution | Automatic entry point remains rejected | Gate preserved; positive behavior not implemented |

## Focused verification

New/extended suites:

- `tests/test_automatic_solve_lifecycle.py`: deadline math, typed stop, process/workspace ownership,
  unsafe lock rejection, and budget failure between last-task success and parent settlement.
- `tests/test_automatic_solve_deadline_integration.py`: 18 native offline integration cases, all
  passing; local model responses are fixtures, and candidate/evaluator programs are fresh fixtures.
- `tests/test_automatic_solve_status.py`: 13 cases passing, including answer identity, read-only
  status, bounded diagnostics and terminal winner behavior.
- `tests/test_solve_budget_propagation.py`: 23 cases passing, including timeout ceilings,
  independent scoring admission and typed stops surviving broad exception handlers.
- `tests/test_automatic_solve_orchestration.py`: Store, scheduler, child outcome, delivery and legacy
  compatibility; output-publication Store tests cover rejection after failed/cancelled parents.
- `tests/test_automatic_cancel_phase_b.py`, `tests/test_automatic_runtime_processes.py`,
  `tests/test_evaluator_bundle_process_ownership.py`, `tests/test_candidate_process_release.py`,
  and `tests/test_process_ownership.py`: Phase B cancellation, process registration, cleanup
  ordering, ownership release, and late-response coverage. The child-stage cleanup fixture
  includes a claimed parent orchestration attempt, matching the production lifecycle.

The final Phase B focused verification command passed **146 tests in aggregate** across the
cancellation/deadline, population, candidate evaluation/evaluator/evidence, snapshot evaluator,
and process ownership suites. The cleanup regressions also prove that a new launch cannot replace
a registration retained after failed cleanup, and that cancellation blocks later generation,
execution, scoring and delivery when no wall timeout is configured.

The policy/preparation/automatic-bundle/orchestration compatibility command passed 227 tests.
Preparation-recovery/status/deadline integration passed 42 tests before the final five boundary
cases were added. A subsequent 28-test status/integration run and independent 15-test integration
run passed. Final Store/Controller/run-budget/lifecycle/status refinement passed 46 tests. The
materialization and attestation compatibility suites passed 186 tests after the additive task
schema fixture update; publication and lifecycle boundary suites passed 134 tests.

Ruff for all `src` and `tests`, compileall, Specify prerequisites with `--require-tasks
--include-tasks`, and `git diff --check` pass. Local Markdown links are checked before commit.

## Full regression

The 2026-09-21 Phase B two-stage rerun is recorded in `.lunar/test-results/feature142-phase-b-20260921/`:

- Current working tree: **8636 passed, 1 skipped, 24 deselected**, 0 failures and 0 errors,
  exit 0 (`current.xml`).
- Frozen Feature 123 registration stage: **24 passed**, 0 skipped, 0 failures and 0 errors,
  exit 0 (`frozen123.xml`).

The current stage executed 8637 collected tests; the 24 deselected nodes are the immutable
historical registration selection. The frozen Feature 123 stage recorded 24 passed tests. These
reports are the final Phase B checkpoint. An accidentally started duplicate run removed the earlier
`feature142-phase-b-final/current.xml` before being stopped; that incomplete directory is not the
final evidence. This rerun restores a complete pair without changing the product or historical
campaign evidence.

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

The 2026-09-21 readiness audit additionally checked the pushed product `65d9ae2` on
[GitHub Actions run 35522272395](https://github.com/vchive/Lunar-Agent/actions/runs/35522272395).
Its Linux/Python 3.11 installation steps passed, but `Run tests` exited 1 and static checks were
skipped. Python 3.12 and 3.13 were cancelled by matrix fail-fast after that failure. Public metadata
does not identify a failing test or distinguish current from frozen123 failure; full logs require
authentication and no report artifact was uploaded. Root cause and cross-platform acceptance
remain open. The retained local passing reports above are unchanged and are not a claim that
the remote CI matrix passed.

Offline correctness here does not establish evaluator quality, current-model task success,
WebAgent parity or successful real automatic multi-file delivery. Feature 139 remains preparation
1/1 and primary/joint 0/1. Phase C still requires detached solve/resume/answer routing, exact
policy restoration, once-only answer acceptance, exclusive worker ownership, launch/exit and
stale-worker recovery, and foreground/background equivalence with live cancellation. A separately
scoped real acceptance also remains outstanding; this checkpoint does not claim the whole feature
or system release is complete.
