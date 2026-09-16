# Feature 113: Current-version automatic multi-file acceptance

## Outcome

Independently register and run two real GLM-5.2 attempts on product commit `c977eb4` using
`solve --evolve --multi-file`. Measure completed multi-file delivery and generated evaluator
agreement with an independent exhaustive oracle. This is a descriptive acceptance sample, not a
WebAgent comparison or evidence that evolution improves over ordinary solving.

## Acceptance

1. Commit and push fixed tasks, inputs, model/gateway identity, code hashes, attempt order,
   budgets, independent checkers and holdouts before any provider request.
2. Run budget selection then worker assignment once each, sequentially. No task replacement,
   repair, clarification answer, candidate retry outside the fixed population, or model fallback.
   Preserve every planned slot, including setup, compiler, audit, generation and delivery failures.
3. Bound each attempt to 1200 seconds, each request to 180 seconds, at most 16 model requests,
   and stop further spending at 160000 observed tokens or unavailable usage. Token accounting
   is an observed stop threshold: one response can exceed it because the native request has no
   server output-token cap. Interrupted request consumption and monetary cost may remain unknown.
4. Verify portable delivery and independently compute feasibility, objective and exhaustive
   optimum. Require at least two delivered Python files for the multi-file completion metric.
   The primary completion also requires the supervisor and worker to return successfully;
   timeout or interruption leaves official quality null. Report model/budget-envelope verification
   separately: unknown consumption never becomes a claim of complete accounting. A delivered
   feasible solution may coexist with an earlier failed candidate, which remains recorded.
   Audit the frozen generated evaluator/contract against preregistered holdouts, keeping product
   schema rejection separate from evaluator success. No execution error counts as correct rejection.
5. Report fixed-denominator completion, per-task quality/null, timings, known usage, failures and
   limitations. Keep historical measurements unchanged. Commit/push evidence and actionable findings.

## Scope

Measurement code only. The native product remains frozen. No WebAgent, external producer,
normal-vs-evolution comparison, model probing, hidden retries or new user attestation.
