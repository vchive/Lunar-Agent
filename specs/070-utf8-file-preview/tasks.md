# Tasks: UTF-8 File Preview Boundaries

- [x] T070-01 Document the observed boundary failure and freeze the isolated scope.
- [x] T070-02 Add failing multibyte-cutoff and strict-invalid-data regression tests.
- [x] T070-03 Implement strict prefix decoding and update the tool parameter explanation.
- [x] T070-04 Run focused and adjacent tests, independent review, full verification and commit.
- [x] T070-05 After Feature 069 termination/audit, integrate the reviewed change and update HANDOFF.

No new real evaluation is included. Feature 069 configuration, source, tests and attempts remained
frozen throughout the measurement; integration followed its final evidence seal.

Verification on 2026-09-10: the initial 44-case matrix failed 9 cases and passed 35 on the
original implementation, then passed all 44 after the fix. A separate synthetic 28,878-byte file
reproduces the actual 20,000-byte cutoff and now returns the complete 19,998-byte prefix.
The final full suite passed 919 tests (37.41 seconds), with import paths explicitly set to this
worktree. Independent review found no blocking issue; 44 boundary and 73 adjacent tests passed
independently before the final synthetic case was added and reviewed. Ruff, Specify prerequisites
and diff checks passed. No provider was called, and the live measurement files remain unchanged.

T070-05 completed on 2026-09-10: Feature 069 final results were independently audited and sealed
in 26fc4a4, then 070 was integrated in 6def340 and 071 in caf9a1f. The combined main checkout
passed 127 focused tests across UTF-8, argv diagnostics, AgentLoop, budget tools, runtime and
transcript behavior (12.99 seconds), plus Ruff, Specify prerequisites and diff checks. Independent
integration review confirmed src/tests match the previously reviewed 071 tree and all original
measurement scripts, frozen inputs, historical anchors and sealed final evidence remain unchanged.
The isolated 919/946 full-suite records remain applicable; no new provider call or benchmark run.
