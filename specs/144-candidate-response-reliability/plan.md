# Implementation plan

1. Keep the runtime-neutral request boundary. Add an optional fixed response protocol to
   AgentRequest, forward only to explicitly capable runtimes, and apply local system guidance
   to model request copies without changing shared prompt or durable transcript state.
2. Declare the protocol in bundle generation and make prompt examples match the unchanged
   parser. Keep both inline and referenced-context paths within the existing prompt bound.
3. Extend the existing strict receipt projection with optional allowlisted phase/cause fields.
   Canonicalize only known runtime aliases; preserve legacy canonical events. Carry actual
   runtime counts into parser-failure receipts. Use typed failure evidence rather than text.
4. Write offline regressions for request-to-model propagation, reuse/history isolation, legacy
   adapters, prompt examples, strict rejection, receipt persistence, aliases and redaction.
5. Run focused/shared suites, the full two-stage regression runner, Ruff, compileall, quickstart,
   Specify prerequisites and frozen inventories. Obtain independent review, record exact limits,
   update handoff/readiness and commit/push the verified feature.

## Decisions and alternatives

- Do not loosen JSON parsing or extract fenced content: rejection remains deterministic.
- Do not introduce a submit tool or hidden follow-up request: both would change tool budgets,
  runtime capabilities and the definition of a completed attempt beyond this repair.
- Do not require a new keyword on external runtimes: they retain current prompt compatibility.
- No dependency, database migration, network request, measurement replay or automatic retry.

## Data and contracts

AgentRequest gains optional `response_protocol`. AgentLoop invocation accepts the same optional
keyword. The known value is `lunar-evolution-bundle-generation-v1`; omitted values retain old behavior.
The existing bundle response fields (`entrypoint`, `files`, optional `metadata`, `experiment`)
and parser are unchanged. Generation receipts retain schema 1 and identity derivation, adding
only validated optional phase/cause observations. Consumers may not treat either as completion.

This follows the constitution's adapter isolation, durable state, independent verification,
bounded autonomy and tested recovery rules. There are no governance exceptions.
