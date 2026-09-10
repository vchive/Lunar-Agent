# Tasks: UTF-8 File Preview Boundaries

- [x] T070-01 Document the observed boundary failure and freeze the isolated scope.
- [x] T070-02 Add failing multibyte-cutoff and strict-invalid-data regression tests.
- [x] T070-03 Implement strict prefix decoding and update the tool parameter explanation.
- [x] T070-04 Run focused and adjacent tests, independent review, full verification and commit.
- [ ] T070-05 After Feature 069 termination/audit, integrate the reviewed change and update HANDOFF.

No new real evaluation is included. Feature 069 configuration, source, tests and attempts stay frozen.

Verification on 2026-09-10: the initial 44-case matrix failed 9 cases and passed 35 on the
original implementation, then passed all 44 after the fix. A separate synthetic 28,878-byte file
reproduces the actual 20,000-byte cutoff and now returns the complete 19,998-byte prefix.
The final full suite passed 919 tests (37.41 seconds), with import paths explicitly set to this
worktree. Independent review found no blocking issue; 44 boundary and 73 adjacent tests passed
independently before the final synthetic case was added and reviewed. Ruff, Specify prerequisites
and diff checks passed. No provider was called, and the live measurement files remain unchanged.

T070-05 stays open until Feature 069 terminates and its final evidence is audited.
