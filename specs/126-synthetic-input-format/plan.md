# Plan

Expose `validate_input_format(format_name, content)` in data_profile, using its existing UTF-8 and
record parser without computing/storing a profile. Share supported-format dispatch with private
profiling so both paths enforce the same record rules. Normalize parser recursion/Unicode failures
to DataProfileError; at preflight expose only a fixed compiler/audit format error without data or
parser prose. Validate the complete suite at the start
of `_preflight`, before creating workspaces or starting processes, for both compiler and auditor
and both invocation modes. Preserve the original load/parser path for frozen bundles.

Extend shared response instructions with format admission and existing structural constants.
Do not include real input values, compare synthetic statistics against a private profile, or infer
field schemas from natural language. Do not add a second JSON/CSV parser. Per-probe validation
inside the execution loop was rejected because a malformed later probe would allow earlier
harness execution; whole-suite admission has a clearer boundary.

No stored data model or wire contract changes, dependencies, migration or constitution exception.
New generation is stricter while existing frozen identities and terminal recovery remain valid.
Keep detailed stage/reason diagnostics out of this scope so admission can be independently tested.

Write parser/profile parity and preparation tests from fresh synthetic fixtures, run the relevant
regressions and 112 recovery quickstart, review independently, then freeze implementation and run
the established two-stage full regression. Preserve all historical measurement/test bytes and
record checks and limitations in validation.md. Update current status documents, commit and push.
