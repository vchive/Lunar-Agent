# Feature 131: Small multi-file acceptance recheck

## Scope

Feature 129 used one real native automatic multi-file attempt and stopped when the contract
compiler returned a complete contract without the required top-level `status=compiled` envelope.
Feature 130 added complete `needs_input` and `compiled` envelope examples while preserving the
strict parser. Recheck the same small task once on fixed product
`c730483080d5f53e5bb2d24e4bb2d2d9f45e984e`, using a new denominator and campaign root.

This is a same-task recheck, not a strict causal experiment. Feature 129 remains sealed at 0/1.
No old response, evaluator, candidate, delivery or campaign state may be reused or repaired.

## Registered conditions

Keep Feature 129's task bytes, plain-language goal, eight holdouts, provider identity, native CLI,
population seed and every budget unchanged. The input is `{"limit":3}` plus newline. The required
output is `output/result.json` with an integer value in `[0, limit]`; maximize value. Require at
least two distinct lowercase `.py` source paths through native `python_file_count` minimum 2.

Use native `solve --evolve --multi-file`, GLM-5.2, population size 2, offspring 1, islands 1,
max rounds 1, stagnation rounds 3 and seed 129. Allow at most 20 provider requests, 600 seconds per
request, 2400 seconds total, 160000 observed tokens and 5 seconds per conditional holdout. There is
one planned attempt and no campaign retry, resume, response repair, fallback or replacement.

Pin Feature 128's successful preparation manifest and Feature 129's failed attempt manifest by
SHA-256. Register and push the product, measurement, tests, task, provider and budgets before the
first real request. The new root is
`.lunar/acceptance131-glm-5.2-small-multifile-20260917` with only `attempt-001`.

## Outcomes

Primary success is one verified source-aware feasible parent delivery. Secondary success is exact
agreement on all eight registered evaluator holdouts after verified preparation. Joint success
requires primary success, 8/8 holdouts and verified process cleanup. Official quality and optimality
gap require a completed worker, zero native exit and verified cleanup. Partial observations remain
visible but do not become official quality.

Private model responses and generated source remain private. Publish bounded request accounting,
transport metadata, fixed preparation diagnostics, output/source evidence and retained file hashes.
Summarization reads retained evidence only and never executes generated code.

## Limits

One synthetic recheck cannot establish general correctness, reliability, evolution benefit,
WebAgent parity or that Feature 130 alone caused any difference. Source file count does not prove
imports, helper use or input reading. The eight integer holdouts do not cover all bool/float rules.
Observed token accounting is not a server-side cap, provider defaults and cost remain uncontrolled,
and native process restrictions are not an OS sandbox.
