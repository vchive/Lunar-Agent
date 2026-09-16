# Feature 120: Real acceptance within supported verification scopes

## Outcome

Independently measure two GLM-5.2 attempts on product
`c5695088c83bf69188bd7ae222056c8b63233656` after Features 118 and 119. The old campaigns
remain frozen at their separate 0/2 denominators. This campaign changes the task wording:
source delivery requires two distinct lowercase `.py` paths, including empty files, with a
hard `verification_scope=source`, `source_check={kind:python_file_count,minimum:2}` constraint.
It does not require helper imports, standard-library-only dependencies, or actual input reads.
Those old behavioral requirements are not satisfied or certified by counting files.

## Acceptance

1. Freeze a new manifest, independent root/slots, product/runtime/measurement hashes and old
   campaign evidence. Commit and push registration before invoking any model.
2. Preserve the original mathematical inputs, output feasibility rules, objective, independent
   exhaustive oracle, all 24 output holdouts, task order, GLM-5.2/gateway, population 2+1 and seed113.
   Exact new goals are registered. Do not silently weaken or add constraints after launch.
3. Preserve117 limits: 600 seconds per HTTP/local process and ordinary Agent invocation,
   3600 seconds per task, at most16 requests, 160000 observed-token stop threshold,
   four normal tool steps, one worker, no exec tool/memory/history, native sampling defaults.
   Maximum two-hour execution allowance plus bounded cleanup; postrun audit is separate.
4. Run each of the two slots once. No answers, retries, resume, replacement, repair calls,
   fallback model, budget changes or old slot reopening. Unknown cleanup prevents later slots
   without reducing the planned denominator. Unknown provider consumption stays unknown.
5. Primary completion requires native success, a verified source-aware delivery bound to the
   parent/child/contract, the registered hard minimum2 source checker with passing evidence,
   and independently feasible outputs. A contract that omits or changes the source requirement
   cannot count as successful even if its delivered bundle happens to contain two files.
6. Evaluate available frozen output harnesses on registered holdouts, independently check the
   delivered outputs, and preserve every failure. Failed official quality and gap remain null.
   Report primary and budget-envelope success separately, each /2. Private response prefixes
   are bounded/redacted and excluded from public reports.
7. This is descriptive acceptance of changed product and task scope. It is not a causal
   comparison, proof of the old behavioral requirements, nor a normal-mode/WebAgent benchmark.
