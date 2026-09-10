# Tasks: Correctable Command Argument Diagnostics

- [x] T071-01 Specify the observed error and isolated diagnostic-only scope.
- [x] T071-02 Add failing input-diagnostic and subprocess-compatibility tests.
- [x] T071-03 Implement the diagnostic and update the existing tool parameter explanation.
- [x] T071-04 Verify model-led correction, original transcript and cumulative usage/tool steps.
- [x] T071-05 Complete offline checks, independent review and isolated branch commit.
- [x] T071-06 Integrate after Feature 069 termination/audit and update the main handoff.

No new real evaluation or automatic retry is included.

Verification on 2026-09-10: initial tests failed 7 cases and passed 18 on the prior implementation.
The final 27-case diagnostic suite passes, including deep JSON parse failure and ValueError
compatibility. The explicit worktree-source full suite passed 946 tests (35.26 seconds).
Independent review found no blockers and passed 44 targeted command/budget/provider-schema tests.
Ruff, Specify prerequisites and diff checks pass. The model-led correction fixture records two
tool calls and one fake subprocess dispatch, preserves both argument types in the transcript,
and carries 15 tokens/cost units over all three model responses.

Implementation was developed in isolation on Feature070 without changing the active measurement.
T071-06 completed on 2026-09-10: final Feature069 evidence was sealed/published in 26fc4a4 before
070 merge 6def340 and 071 merge caf9a1f. Main-runtime import paths were verified and 127 targeted
tests passed (12.99 seconds), covering both new suites plus AgentLoop, budget tools, runtime and
transcript behavior. Ruff, Specify prerequisites and diff checks passed; independent integration
review confirmed src/tests/.specify equal the reviewed 5a39aa4 tree and the original measurement
and final evidence remain unchanged. The prior isolated 946-test full-suite pass is retained.
The active feature points to 071. There were no new provider requests, WebAgent executions,
benchmark attempts or automatic corrections/retries introduced during integration.
