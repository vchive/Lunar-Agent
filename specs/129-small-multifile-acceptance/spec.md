# Feature 129: Small real automatic multi-file acceptance

## Scope

Feature 128 passed one real evaluator preparation and eight integer holdouts. The missing evidence
is a real automatic solve through contract preparation, evaluator compilation/audit, population
generation, execution, independent evaluation, selection and parent delivery. Exercise this path
once on fixed product b9518570a18e25ad784d00ba864a18ee8e30ac80. No product changes.

## Registered task and budget

Read limit.json with exact bytes {"limit":3} plus newline. Produce output/result.json containing
value, a JSON integer (not bool/float) between zero and limit. Feasible suboptimal values are valid;
maximize value, with quality and combined_score exactly value. Invalid values score zero with
null quality and valid-value error code. Require at least two distinct lowercase .py source paths,
using native source_check python_file_count minimum 2. File count does not prove imports, helper
use, syntax, dependencies or actual input reading. Do not request unsupported behavioral checks.

Use native CLI solve --evolve --multi-file, GLM-5.2 and the same provider identity as128. Contract
and evaluator are generated fresh; no registered/manual contract is injected. No tools/history for
the three native isolated preparation calls; candidate Agent uses existing tools, no exec tool,
memory or previous sessions. Population size2, offspring1 per island, islands1, max_rounds1,
stagnation_rounds3, seed129; keep native generation and selection. Agent max_steps4, workers1,
native max_retries1. No campaign retry/resume/repair/fallback/replacement or manual extra request.

Each request <=600s, supervisor <=2400s including all local work and conditional holdouts,
max20requests, observed160000-token stop, 5s/holdout. Token observation is not a server cap.
Native stream:false; temperature/max_tokens/reasoning_effort/response_format omitted. Unknown
provider defaults and costs remain unknown. One attempt starts once and consumes its denominator.

## Verification and outcomes

Register and push all product/runtime/measurement/test/task/input/holdout/provider/budget pins
before any model request. New root .lunar/acceptance129-glm-5.2-small-multifile-20260917 with sole
attempt-001. Preserve passive request/transport/private response observation. Only fixed safe
preparation status/local diagnostic fields may be published; no private response or source text.

Primary source-aware feasible parent delivery /1 requires successful native parent and child,
bound delivery event/manifest, exact final output/artifact copies, verified automatic preparation,
registered source contract and portable source evidence, plus an independent mathematical check.
Report optimality separately (known optimum3); feasibility does not require optimality. Verify
native contract's single input/output, maximize objective, valid-value output constraint and
python_file_count minimum2 source requirement before accepting evidence.

After native solve returns and preparation is verified, run the same eight integer evaluator
holdouts as128 once each, inside the remaining wall budget, even if later candidate work failed.
Model-request stops (including provider failure, request count or token threshold) prevent more
model calls but do not suppress these local checks; the supervisor wall deadline still applies.
Never run a candidate again. Record each holdout before proceeding; summarization only reads
retained evidence and verifies the frozen evaluator without executing it. Secondary holdouts /8
and joint feasible delivery plus8/8 plus verified cleanup /1 are separate. Missing/unrun checks
are not successes. A failed or partial attempt has null official quality/gap; retained observations
remain available. No real terminal resume is performed; existing offline idempotence tests apply.
Official quality/gap additionally require the worker to finish and the supervisor to exit zero
with verified cleanup. Primary delivery evidence and secondary holdouts remain separately visible.

## Limits

One synthetic task is not general correctness, performance, evolution benefit or WebAgent parity.
Eight integer holdouts do not cover all boolean/float rules. Source count can include empty files.
Native process restrictions are not an OS sandbox; local holdouts are not in model context but
are locally accessible. All historical campaigns remain sealed:113/115/117/120 each0/2,
123/125 each0/1,128 preparation1/1 and holdouts8/8; no historical denominator changes.
