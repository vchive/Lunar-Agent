# Validation

- Focused benchmark comparison/result and evidence binding tests: **11 passed**.
- Ruff and compileall passed for the changed Python modules.
- The original full-regression count of 3854 was a reporting error: pre-repair pytest collection
  found 3853 tests. The follow-up full run below is recorded from pytest and its JUnit report.
- No external framework, model, provider, evaluator, remote service or campaign was started.
- Evidence binding is observational: it checks local bytes and does not make an effectiveness claim.

## 2026-09-15 follow-up

- Before implementation, deterministic open-substitution and unbounded-read regressions produced
  **3 failed / 5 passed**; malformed result validation produced **18 failed / 4 passed**.
- After repair, six benchmark test files: **88 passed** (0.33s).
- Installed `lunar-agent` CLI smoke: accepted a valid local evidence fixture, returned exit 2 with
  `benchmark_result_evidence_changed` after a file edit, and left home absent throughout.
- Legacy receipt canonical data, result ID and digest match the pre-repair implementation.
- Independent final review found no blocker; 144 additional malformed field probes produced no
  unexpected exception. Result file path restrictions are explicit in spec and quickstart.
- Full regression: **3919 passed in 221.00s**, with JUnit confirming 0 failures/errors/skipped.
  The three new test files contain 66 tests, included in both the focused and full runs.
- Full `src`/`tests` Ruff, compileall, Specify prerequisites and diff check passed.
- All 601 tracked files under Features 051/074/076/078/082 match `027a235`.
- Only local fixtures were used. No live framework, model, provider, remote service or campaign ran.
