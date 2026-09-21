# Validation

- Before file-boundary implementation, new task/plan reader regression: **4 failed / 2 passed**.
  The deterministic open substitution and oversize-before-read checks reproduce actual old gaps;
  the read-time mutation test exercises the new descriptor-read path.
- Legacy 099/100 golden receipt ID/digest values were recorded from `d81145f` and remain unchanged.
- Installed `lunar-evolution` CLI smoke: valid caller pin + plan + receipt + evidence accepted; changing
  a benchmark release with the receipt retained was rejected with a fixed mismatch code; home absent.
- Independent review initially reproduced mutated task DTO path/size bypasses; strict DTO replay
  now rejects both before file opens. The review reran the cases and found no remaining blocker.
- Full src/tests Ruff, compileall, Specify prerequisites and diff check passed.
- 601 tracked files in Features 051/074/076/078/082 match `027a235`.
- All benchmark test files: **187 passed in 0.74s**. Four new files contain 91 tests, included in
  both the focused and full runs.
- Full regression: **4010 passed in 229.10s**; JUnit confirms 0 failures/errors/skipped.
- This feature uses local fixtures only and does not start a framework, model, evaluator, provider,
  remote service or campaign. It produces no effectiveness or WebAgent parity conclusion.
