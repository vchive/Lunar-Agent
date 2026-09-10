# Tasks: Corrected Staged Workflow Measurement

- [x] T074-01 Define the fixed two-slot corrected workflow protocol and scope.
- [x] T074-02 Implement and test minimal two-slot registration, bindings and pinned native reuse.
- [x] T074-03 Verify offline preaudit/dry-run and postrun projections; independent cross-review.
- [x] T074-04 Materialize, independently audit, freeze, commit and push registration/reports.
- [x] T074-05 Launch exactly once and observe both fresh attempts through termination.
- [x] T074-06 Independently audit final evidence/processes, seal results and update handoff.

Pre-materialization verification: 137 new measurement/reporting tests passed. The complete
isolated offline scenario set passed 239 tests with network and CC Switch access blocked and
temporary fixture workspaces. Ruff, Specify and diff checks passed; independent implementation
and protocol cross-review found no remaining blocker. Source c28e498 and all old campaigns are
unchanged. Actual registration reports and committed launch evidence remain separate steps.

T074-04 completed: the independently audited manifest and mirrored 239-test dry-run were
committed/pushed as 27f7124b28ef9a7318c5f574a9ac97b16a718b9c before exclusive launch.
T074-05 is active: both subjects started at 2026-09-10 14:10:22 +0800. Dispatcher PID/PGID 77166,
worker PIDs/PGIDs 77318 (slot 1) and 77317 (slot 2), observed subject PID/PGID 77319 and 77320.
The first independent partial audit passed 181 evidence hashes; both were still in Master.
No plan, Build or score had been accepted. The launch must never be repeated.

Final closure: both slots terminated; sheet subject reached model/timeout at 1200.203 seconds,
postal subject stopped at 167.136 seconds with runtime_failed and a deterministically reproduced
public score-vocabulary rejection after successful JSON parsing. No accepted plan/Build/receipt/
harness; scores and complete failed usage/cost remain null. Independent final acceptance and root
reverification passed 205 evidence hashes, including source37/frozen99/history18. Known PIDs/PGIDs
and visible argv/cwd associations showed no remaining campaign process, with visibility limitations
recorded in final-process-check.json. Results and diagnostics are sealed before integrating075.
