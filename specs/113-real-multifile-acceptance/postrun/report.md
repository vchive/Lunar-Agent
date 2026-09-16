# GLM-5.2 automatic multi-file acceptance: 0/2 completed

The two preregistered attempts both failed during contract intake. Neither reached automatic
evaluator preparation, candidate generation or delivery. This run establishes an entry-path
reliability failure; it supplies no measurement of multi-file solution quality, generated evaluator
correctness, or improvement from evolution.

Registration `10b844b` was pushed before launch. Product bytes were fixed at
`c977eb4da528cb1ab2a98958cf0b54a01869d347`; the manifest digest remains
`9f30acf0db6e672331c86a3efc46a964fb71d4c1d8a4cd2fe287ee9ec8e6e367`.
Both native responses reported `glm-5.2`. Each task received exactly one provider request and one
completed response. No retry, clarification answer, model fallback or replacement slot occurred.

| Task | Completion | Failure recorded by product | Quality | Wall seconds | Known tokens |
| --- | --- | --- | --- | ---: | ---: |
| Budget selection | Failed | compiler response must be one strict JSON object | null | 89.484 | 7,282 |
| Worker assignment | Failed | evolution contains unknown fields | null | 131.041 | 8,676 |

Primary completion and completion with a verified execution envelope are both **0/2**. The two
independent reference optima (37 and 39) are not model scores. No frozen evaluator exists, so the
24 planned synthetic holdouts were not invoked; their agreement rates remain unavailable.

Known usage totals **15,958 tokens**: 2,771 input and 13,187 output. Each request has complete
reported usage and a matching response model, with no pending request or guard stop. Monetary
cost remains unknown. Both processes exited normally with product failure (exit code 1), and
the supervisor found no remaining observed descendants. The combined slot wall time was
220.524 seconds. Neither the individual HTTP nor total attempt deadline was reached.

## Confirmed finding and next repair

Read-only source inspection and an offline request-shape reproduction found that
`RuntimeContractCompiler.compile()` calls the general runtime's `run()`. With `--agent-loop`,
this installs the general assistant system prompt asking for a final summary of changed files
and checks, and exposes file/clarification tools. That conflicts with the compiler's pure JSON
protocol. The existing `run_isolated()` path already supplies a stateless machine-readable system
prompt without those tools or history; contract intake should use that path when available.

The compiler prompt also names optional `evolution` without enumerating its complete allowed
fields, while the parser rejects unknown fields. Its schema guidance should specify exactly
`strategy`, `max_rounds` and `stagnation_rounds` and retain strict rejection.

The failed raw model responses were not retained. Therefore the first failure cannot be assigned
to markdown fences, truncation or any particular syntax, and the exact extra field in the second
response is unknown. The prompt/runtime conflict is independently confirmed, not proven to be
the only cause of these responses. Repair it under a new feature with offline regressions;
do not reopen either frozen attempt. Any new effectiveness claim needs a new registration.

## Evidence and limits

- [Structured results](results.json), [failure diagnostics](diagnostics.json), and
  [private artifact hash inventory](evidence.json).
- Retained local campaign: `.lunar/acceptance113-glm-5.2-multifile-20260916/`.
- This is two hand-authored tasks, one attempt each, with no concurrent control. It does not
  estimate general success rates or compare against ordinary solving or WebAgent.
- The older GLM-5.2 ordinary-workflow successes remain historical evidence for their recorded
  version and configuration. They do not establish current-version parity.
