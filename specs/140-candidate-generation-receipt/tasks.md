# Tasks

- [x] T001 Freeze the event schema, identity bindings, safe-field allowlist, and one-event rule.
- [x] T002 Trace generator and controller persistence at the pinned product commit.
- [x] T003 Implement the bounded payload builder and atomic Store append.
- [x] T004 Add read-only inspection and tamper/duplicate/budget regression tests.
- [ ] T005 Run the full regression, Feature 139 offline tests, Ruff, compileall, and historical
      SHA inventory; the focused suites and static checks pass, while the legacy measurement123
      setup still rejects the changed product commit. Re-run the historical suite from its pinned
      product snapshot before closing this task.
