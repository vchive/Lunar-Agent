# Tasks: Corrected Staged Workflow Measurement

- [x] T074-01 Define the fixed two-slot corrected workflow protocol and scope.
- [x] T074-02 Implement and test minimal two-slot registration, bindings and pinned native reuse.
- [x] T074-03 Verify offline preaudit/dry-run and postrun projections; independent cross-review.
- [ ] T074-04 Materialize, independently audit, freeze, commit and push registration/reports.
- [ ] T074-05 Launch exactly once and observe both fresh attempts through termination.
- [ ] T074-06 Independently audit final evidence/processes, seal results and update handoff.

Pre-materialization verification: 137 new measurement/reporting tests passed. The complete
isolated offline scenario set passed 239 tests with network and CC Switch access blocked and
temporary fixture workspaces. Ruff, Specify and diff checks passed; independent implementation
and protocol cross-review found no remaining blocker. Source c28e498 and all old campaigns are
unchanged. Actual registration reports and committed launch evidence remain separate steps.
