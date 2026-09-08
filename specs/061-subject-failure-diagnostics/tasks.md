# Tasks: Bounded Subject Failure Diagnostics

- [x] T061-01 Record the real failure, evidence boundary and minimal diagnostic contract.
- [x] T061-02 Add and observe failing deterministic subject/runner regression tests.
- [x] T061-03 Implement strict bounded diagnostic schema and safe file helpers.
- [x] T061-04 Emit safe subject diagnostics and clarify frozen input prompts.
- [x] T061-05 Collect normal/deep diagnostics without changing score or recovery authority.
- [x] T061-06 Complete adversarial/compatibility tests, review and full quality gates.
- [x] T061-07 Document results and continue with a historically recorded WebAgent solver model.

Validation: the initial nine deterministic regressions all failed against the original HEAD.
After implementation, all 634 repository tests passed in 24.65 seconds. Ruff, compileall,
`uv build`, Feature 061 Specify prerequisites, and `git diff --check` passed. Independent review
found no blocking issue; classification and publication failures both preserve the original error.

The real GLM5.1 normal subject executed and timed out at its 900-second budget after 12 observed
model turns and 13 tool-result events. Its request-bound model/timeout sidecar was collected;
public inputs remained unchanged, no success receipt/harness/candidate was produced, and no score
is available. Failure usage is unknown. The ignored experiment directory retains the evidence;
HANDOFF documents the model choice and independent-score boundary without relabeling GPT history.
