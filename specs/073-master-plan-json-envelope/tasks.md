# Tasks: Deterministic Master JSON Envelopes

- [x] T073-01 Specify observed formatting failure and isolated acceptance contract.
- [x] T073-02 Add failing tests and implement bounded unambiguous envelope parsing.
- [x] T073-03 Verify raw/fenced handoff, usage carryover and failure/no-harness paths with native fixtures.
- [x] T073-04 Run isolated checks and independent review; commit and push the isolated branch.
- [x] T073-05 Integrate only after Feature072 final audit/seal; verify main and update handoff.

Verification on 2026-09-10: failure-first parser tests ran before the helper existed. Final parser
suite has 93 passing cases; 10 native integration cases cover raw/fenced equal cumulative usage
and elapsed budgets, isolated Build history, preserved redaction, sole native harness dispatch
after accepted receipt, and six rejection paths with no Build/receipt/harness/retry.
The combined targeted set passed167 tests. The isolated full tests plus072 postrun tests passed
1147 tests (36.19 seconds); explicit PYTHONPATH imports point to this worktree. Ruff, Specify and
diff checks passed. One old072 isolated-test assertion now expects the new bounded
WorkflowCheckpointError instead of JSONDecodeError; the frozen main test remains unchanged.
No real model request, historical candidate execution, or alteration to the active072 occurred.
Independent review found no blocking issue and independently reran167 targeted tests. Envelope
ambiguity rejection, bounded errors, existing redaction, cumulative accounting and native receipt
authority were checked. The isolated branch is ready for integration after072 final evidence seal;
T073-05 stays open while the measured main source remains frozen.

T073-05 completed after072 final evidence was sealed/pushed in0a7f90e. Reviewed isolated
implementation dd4d7f5 was merged as228b213. Main src/tests/.specify exactly match that reviewed
tree; actual staged_workflow import points to the main checkout.167 targeted main tests passed
(0.88 seconds), with Ruff, Specify and diff checks passing; the isolated1147-test full-suite pass
is retained.072 measurement scripts, registration, final audit/report/process evidence are unchanged
from the sealed commit. Its live-source auditor is expected to reject the newly changed parser;
historical manifests and results must never be rewritten to satisfy it. No further real attempt
or model request was introduced by integration;073's effect on final solution validity is unmeasured.
Independent integration review confirmed merge parents/seal ordering and byte equality with the
reviewed source/tests and sealed072 reports. A read-only post-merge072 live audit returned the
expected rejection for changed source, without dispatching or altering any historical evidence.
