# Validation

134 new synthetic tests passed: 57 contract framing and 77 verification scope/CLI tests. The
contract-related six-file regression passed 160 tests; existing bundle preparation and recovery
regression passed 171 tests in 48.07 seconds, with zero JUnit failures/errors/skips. Additional
combined framing/schema/preflight checks passed 119 tests. These overlapping checks are reported
separately, not summed as independent coverage.

The contract framing implementation and capability tests were delegated independently; the
capability test review found no product discrepancy. It covers both invocation modes, hard/soft
scope declarations, full coverage for partial requirements, legacy digest compatibility, no-call
failure, persisted CLI state, malformed diagnostic rejection and terminal recovery behavior.

The Feature 112 subprocess quickstart passed: scores 1, 2, 6, 7; final parent delivery scored 7;
contract/compiler/auditor/Agent/candidate calls remain 1/1/1/4/4 after terminal resume, with one
delivery copy. Log: `/private/tmp/lunar118-quickstart.log`.

Full regression passed against frozen implementation/test bytes: **5818 passed, 1 skipped in
380.77 seconds**, JUnit zero failures/errors. Logs: `/private/tmp/lunar118-full.log` and
`/private/tmp/lunar118-full.xml`. All nine changed implementation/test files retain their pre-run
SHA-256 values; no product or test edits followed the final full regression. Ruff, compileall,
installed CLI, Specify prerequisites and 117 local documentation links passed. Historical
113/115/117 and older frozen measurement directories are unchanged.
No new real model request, slot retry, response replay or external framework execution is included.

Known limits: source and execution requirements are diagnosed as unsupported, not implemented.
The explicit scope is a declaration and cannot prove its own semantic correctness. Unscoped
legacy contracts keep previous assumptions and full hard probe coverage. Strict framing support
is local to contract intake; evaluator/Agent candidate parsers are unchanged. No server timeout
cause or real completion-rate improvement is established by these offline checks.
