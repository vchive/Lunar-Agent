# Tasks: Correctable Command Argument Diagnostics

- [x] T071-01 Specify the observed error and isolated diagnostic-only scope.
- [x] T071-02 Add failing input-diagnostic and subprocess-compatibility tests.
- [x] T071-03 Implement the diagnostic and update the existing tool parameter explanation.
- [x] T071-04 Verify model-led correction, original transcript and cumulative usage/tool steps.
- [x] T071-05 Complete offline checks, independent review and isolated branch commit.
- [ ] T071-06 Integrate after Feature 069 termination/audit and update the main handoff.

No new real evaluation or automatic retry is included.

Verification on 2026-09-10: initial tests failed 7 cases and passed 18 on the prior implementation.
The final 27-case diagnostic suite passes, including deep JSON parse failure and ValueError
compatibility. The explicit worktree-source full suite passed 946 tests (35.26 seconds).
Independent review found no blockers and passed 44 targeted command/budget/provider-schema tests.
Ruff, Specify prerequisites and diff checks pass. The model-led correction fixture records two
tool calls and one fake subprocess dispatch, preserves both argument types in the transcript,
and carries 15 tokens/cost units over all three model responses.

Implementation is ready in the isolated branch, based on Feature070. T071-06 stays pending until
the active Feature069 campaign terminates and its final evidence is audited. There were no new
provider requests, WebAgent executions or changes to the measurement checkout.
