# Plan

Keep the two complete JSON examples next to the compiler prompt as the only source of their bytes.
Insert them after the envelope rules and before the contract field reference. Use a small generic
assignment task so the examples contain no historical task material and need no source constraint.
The compiled example includes every required contract field plus valid optional output, evolution,
assumption and evidence shapes. The needs-input example contains only its permitted envelope keys.

Add focused tests that parse the literal examples as strict JSON and pass them through the native
response parser. Verify exact top-level keys, complete contract fields, input/output field types,
shape-only instructions and continued rejection when `status` is removed. Reuse existing isolated
request and response-framing suites for tool/history/framing coverage. Do not alter the parser,
runtime request count, contract dataclasses, persistent state or model transport.

Run focused and related offline regression, the Feature 112 terminal quickstart and the repository's
two-stage full runner because the shared product prompt changes. Run Ruff, compileall, Specify and
whitespace checks, obtain an independent review, document exact results, then commit and push.
