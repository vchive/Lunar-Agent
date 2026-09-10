# Tasks: Public Master Plan Vocabulary

- [x] T075-01 Specify the observed semantic rejection, expanded vocabulary and unchanged authority.
- [x] T075-02 Add failing controller and native handoff regressions; replace obsolete failure fixtures.
- [x] T075-03 Remove semantic text/name checks, reject credential paths, and verify remaining boundaries.
- [x] T075-04 Run isolated targeted/full checks and independent review; record verification evidence.
- [ ] T075-05 Perform root-owned integration after Feature 074 evidence sealing.

Implementation is isolated. No real model, private evaluator or historical candidate execution is
part of this feature. A separate future registration is required to measure solution validity.

Verification on 2026-09-10:

- Explicit `PYTHONPATH` import resolves to this isolated worktree's `src/famou/workflow_checkpoint.py`.
- Before filter removal, controller vocabulary tests produced 16 failures and 68 passes: the
  failures directly cover plan words, ordinary output names, stored reads, and new-name artifact
  validation blocked before reaching the actual symlink check. After removal all 84 passed.
- Before adding path-secret checks, four controller path-secret cases failed and the two native
  actual-key/generic-key path cases incorrectly entered Build. Those cases now reject with bounded
  errors and no persisted accepted Master or Build/receipt/harness, retaining observed usage.
- Native integration first produced 4 failures and 10 passes under the old keyword filter. Its
  expanded final cases cover raw/fenced public vocabulary, named outputs, complete tool pairs,
  checkpoint/resume, local score claims, Build failure, and missing/injected subject receipt gates.
- The quickstart's seven-file targeted set passed **260 tests in 3.72 seconds**. Ruff, Specify and
  `git diff --check` passed. Fixture model and fixture harness behavior use local synthetic evidence;
  no provider or private evaluator is called, and no historical candidate is read or executed.
- Independent review by `sdd_test_matrix` found no blocking issue and independently passed
  **105 targeted tests**, Ruff and `git diff --check`. It checked the expanded public vocabulary,
  credential-path rejection, retained structural and authority boundaries, and native handoff tests.
- The root agent ran the isolated full `tests` suite plus Feature 074 postrun tests with explicit
  `PYTHONPATH=src`: **1316 passed in 37.18 seconds**. The source selection was explicit; this test
  result is independent of the active Feature 074 real measurement and does not change its results.

Independent review is complete. The root agent authorized committing and pushing only the isolated
`codex/master-plan-public-vocabulary` branch. T075-05 remains root-owned and open until Feature 074's
final audit and evidence seal are complete; branch publication does not authorize merging main or
running a replacement attempt. Passing offline tests does not change Feature 074's observed failures
or establish benchmark gain.
