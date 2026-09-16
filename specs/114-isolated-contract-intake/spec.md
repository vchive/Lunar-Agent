# Feature 114: Isolate the contract compiler protocol

## Problem and outcome

Feature 113's frozen real acceptance completed 0/2 tasks. Both stopped at contract intake;
one failed strict JSON parsing and one contained unknown evolution fields. Raw responses were
not retained, so their exact defects and all contributing causes are unknown.

An independent offline request-shape check confirms a separate integration defect:
`RuntimeContractCompiler` calls the general Agent loop, which supplies a system instruction to
summarize changed files/checks and offers tools, despite the compiler requiring one strict JSON
object. Contract intake should use the runtime's existing stateless protocol interface when
available. The prompt should also enumerate the exact permitted evolution schema.

## Acceptance

1. Prefer a callable `run_isolated` without tools, memory or history. Preserve the explicit
   runtime `run` fallback when that optional method is absent and the existing mock compiler.
2. Pass the same bounded goal, clarification answer, workspace and timeout to exactly one
   invocation. An isolated failure must not fall back to a second general invocation or retry.
3. Specify evolution's allowed keys, types, bounds and optional defaults. Preserve strict JSON,
   unknown-field rejection, retired-strategy rejection and the `needs_input` envelope.
4. Test actual Hermes request shape with a local fake model, including compiled/needs_input,
   malformed output, forbidden tool responses and fallback compatibility. Ordinary solving
   keeps its tool loop. Run appropriate regressions and the full product suite after code freeze.

## Limits

This removes a confirmed prompt/runtime conflict; it does not prove the repaired model success
rate. No new provider call, task retry or 113 slot reopening is included. Input schema must be
available in the goal/answer; the stateless compiler cannot inspect staged files with Agent tools.
Unknown material details still require `needs_input`. Adding a structured observed input profile,
retaining bounded failed responses and persisting compiler usage are separate future work.
