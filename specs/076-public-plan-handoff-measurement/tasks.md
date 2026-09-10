# Tasks: Public Plan Handoff Measurement

- [x] T076-01 Define fixed attempts, frozen configuration and acceptance boundaries.
- [x] T076-02 Implement minimal pinned wrappers and focused offline binding/report tests.
- [x] T076-03 Independently review and run guarded native workflow scenarios.
- [x] T076-04 Materialize and independently audit/dry-run; mirror, commit and push registration.
- [x] T076-05 Launch once and observe both fresh attempts through termination.
- [x] T076-06 Independently audit final evidence/processes, seal results and update handoff.

Before materialization:49 preaudit tests,40 runner tests and70 postrun tests passed. The complete
guarded native scenario run passed311 tests, including075 vocabulary/credential-path/receipt gates,
using72 pinned test modules. It inherited no provider environment, blocked network/CC Switch
access, and used only temporary synthetic fixture workspaces. Ruff, Specify and diff checks passed.
Independent protocol and implementation cross-review found no blocker. Source96d5a60 unchanged.

T076-04 completed: actual independent preaudit and311-test dry-run passed,37 source/111 frozen/
24 historical pins verified, reports mirrored and registration committed/pushed as
2916041947c49800b3dda0f5c463014292291aae before launch. T076-05 launched: exactly two subjects
started2026-09-10 17:25:31 +0800. Dispatcher PID/PGID93194, workers93363/93364 and observed
subjects93365/93366. Both slots subsequently terminated; the launch history remains immutable.

T076-05/06 completed: sheet subject1200.259s model/timeout with no plan or Build; postal
subject2190.554s model/model_failed after accepted plan and Build, with solver/output files but no
summary or receipt. Neither used continuation or harness; valid0/2, all scores and complete failed
usage/cost null. Independent final audit and root reread verified225 evidence hashes and all
37 source/111 frozen/24 historical pins. Watcher98576 exited0. The final process check combined80
identity observations, finding no known PID/PGID or visible campaign argv/cwd remnants; visibility
limits are retained. Final audit/report/process evidence and per-slot diagnosis are in postrun/.
No replacement, candidate execution, model probe, WebAgent run or historical score backfill.
