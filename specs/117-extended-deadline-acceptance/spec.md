# Feature 117: Real multi-file acceptance with extended deadlines

## Outcome

Independently register two new GLM-5.2 attempts on product
`9a26a73e38d52b18f003b262a8746bb22496c156`, after Feature 116. Feature 115 completed 0/2:
one contract response took about 120 seconds, then evaluator compilation timed out at 180 seconds;
the other contract request also timed out at 180 seconds. This campaign gives slow stages more
time while retaining the same tasks, population and spending stop thresholds.

## Acceptance

1. Freeze a new manifest, independent campaign/attempt roots, product/runtime/helper hashes and
   historical evidence pins; commit and push the registration before any model request.
2. Preserve 115 task text, inputs, order, model/gateway, population 2+1/seed 113, oracle and all
   24 holdouts. Change only product version and the declared time limits: 600 seconds per
   request/local process and 3600 seconds total per task. The two-task execution allowance is
   two hours, plus bounded process-cleanup overhead; offline registration and postrun audit are
   separate. A longer deadline does not ensure completion.
3. Preserve at most 16 requests/task, 160000 observed-token stop threshold/task, four normal
   tool steps, one worker, no exec tool/memory/history and native sampling defaults. The token
   threshold is not a hard server cap; missing consumption and monetary cost remain unknown.
4. Run each slot once in order. No answers, automatic or manual retries, task replacements,
   repair calls, fallback model, timeout extension during execution or old slot reopening.
5. Preserve the independent delivery, primary and registered-envelope completion definitions.
   Failed official quality/gap stay null. If preparation succeeds, audit the frozen evaluator on
   the registered holdouts; if delivery succeeds, recompute feasibility and quality independently.
6. Retain private bounded/redacted response diagnostics and inspect durable preparation state.
   Report this campaign's /2 separately from 113/115. Product and budgets both changed, so this
   is descriptive acceptance, not an isolated causal test or a normal-mode/WebAgent comparison.
