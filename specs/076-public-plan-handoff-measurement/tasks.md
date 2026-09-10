# Tasks: Public Plan Handoff Measurement

- [x] T076-01 Define fixed attempts, frozen configuration and acceptance boundaries.
- [x] T076-02 Implement minimal pinned wrappers and focused offline binding/report tests.
- [x] T076-03 Independently review and run guarded native workflow scenarios.
- [x] T076-04 Materialize and independently audit/dry-run; mirror, commit and push registration.
- [ ] T076-05 Launch once and observe both fresh attempts through termination.
- [ ] T076-06 Independently audit final evidence/processes, seal results and update handoff.

Before materialization:49 preaudit tests,40 runner tests and70 postrun tests passed. The complete
guarded native scenario run passed311 tests, including075 vocabulary/credential-path/receipt gates,
using72 pinned test modules. It inherited no provider environment, blocked network/CC Switch
access, and used only temporary synthetic fixture workspaces. Ruff, Specify and diff checks passed.
Independent protocol and implementation cross-review found no blocker. Source96d5a60 unchanged.

T076-04 completed: actual independent preaudit and311-test dry-run passed,37 source/111 frozen/
24 historical pins verified, reports mirrored and registration committed/pushed as
2916041947c49800b3dda0f5c463014292291aae before launch. T076-05 active: exactly two subjects
started2026-09-10 17:25:31 +0800. Dispatcher PID/PGID93194, workers93363/93364 and observed
subjects93365/93366. Do not relaunch or mutate frozen files; final acceptance remains pending.
