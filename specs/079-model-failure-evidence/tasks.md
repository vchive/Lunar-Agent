# Tasks: Typed Model Failure Evidence

- [x] T079-01 Draft the observed problem, fixed v3 evidence, compatibility rules and verification plan.
- [x] T079-02 Complete root design review and receive the isolated implementation decision.
- [x] T079-03 Add failure-first loopback HTTP/native regressions and pin existing response acceptance/defaults.
- [x] T079-04 Add exact owned runtime evidence and v3 projection without changing execution or parsing authority.
- [x] T079-05 Verify strict schema, secret exclusion, legacy v1/v2, wrapped/unknown errors and hostile sidecars.
- [x] T079-06 Verify native normal/deep/staged failures leave no receipt/harness/retry/score and preserve ledger rules.
- [x] T079-07 Run isolated focused/adjacent/full checks; record red/green evidence and limitations.
- [ ] T079-08 Obtain independent review; root owns commit/push and integration after Feature 078 evidence sealing.

## Scope and authorization

The isolated worktree is `.lunar/worktrees/feature079-model-failure-evidence`, branch
`codex/model-failure-evidence`, base `fba6ab8cf5b27d3bd1b42f353907a6ae21c25ef9`. The root reviewed
the initial three-document design and then authorized isolated implementation before Feature 078
launch. Feature 078's measured product excludes this work. Product edits are confined to
`runtime.py` and `subject_diagnostics.py`; one new test module, these SDD files and the isolated
Specify selector accompany them. Integration into main remains pending the Feature078 seal.

No real provider call, provider probe, credential loading, private harness, WebAgent run or
historical candidate execution was performed. The tests use explicit fixture credentials and
loopback HTTP or in-memory exceptions. Native harness fixtures are deterministic repository test
scripts, with no private evaluator or external model.

## Verification on 2026-09-10

Before source edits, the new loopback HTTP/native test module had **24 failed and 16 passed in
1.04 seconds**. Every failure was the absent v3/model_failure evidence; existing terminal failure,
no-harness and unknown-score assertions passed before reaching that new assertion. The 16 passing
cases pinned accepted ordinary, legacy and fallback response forms, content conversion, missing
usage and tool-call defaults. The initial implementation then passed all **40 tests in 1.73 seconds**.

The expanded focused set of eight runtime/subject/trial modules passed **313 tests in 20.21
seconds**. Coverage includes normal/deep request-bound collection, a staged Master or Build failure
without retry/harness, and a deep second-round HTTP failure that preserves the first independently
scored fixture round. Typed transport tests preserve the old top-level classification, including
URLError.reason timeouts; six/seven/eight wrapper boundaries pin legacy eight-node cause inspection.
Invalid observed statuses become null, whereas invalid/foreign typed evidence falls back to v1.

Two additional narrow regressions covered the existing explicit non-2xx branch with no HTTPError
and a foreign exception that cannot safely expose its cause. The final new module contains
**88 tests**. Complete isolated regression passed **1447 tests in 38.52 seconds**. Explicit
PYTHONPATH checks confirmed both product imports resolve to this worktree. Full `ruff check src
tests`, Specify prerequisites with tasks, and `git diff --check` passed.

The full suite needs eight ignored historical JSON fixtures also required during Feature 077.
Before running, each main-checkout source was verified against the sealed Feature 074 manifest's
`historical_files_sha256` map, copied exclusively to this worktree, and rehashed. All matched:

- `.lunar/high-score-case-selection-20260909/baseline-audit.json`
- `.lunar/real-eval-glm-5.1-20260909/manifest.json`
- `.lunar/real-eval-glm-5.1-budget-diagnostics-20260909/manifest.json`
- `.lunar/real-eval-glm-5.1-variant-v2-20260909/manifest.json`
- `.lunar/real-eval-glm-5.2-high-score-20260909/{audit,manifest,readiness,summary}.json`

These are report/registration fixtures, not candidates, scripts or credentials. No Feature 078
material was copied, executed or modified. No test or historical registration was changed to
satisfy the isolated environment.

## Remaining limits

Independent cross-review approved the implementation without blockers and independently passed
215 model-evidence/runtime/subject/budget tests, Ruff and diff checks. Root reviewed the typed
projection, cause traversal and failure-only shape classification. Root-owned integration remains
pending until Feature078 is sealed. Passing tests proves the bounded
projection and compatibility contract. It does not recover Feature 076's unknown cause, establish
provider fault, supply failed-request usage, validate a saved candidate or improve measured
valid-solution rate. Rare failures without owned typed evidence retain the existing v1 fallback.
The existing raw exception formatting behavior is unchanged; the new diagnostic does not add raw
logs or cause text to sidecars.
