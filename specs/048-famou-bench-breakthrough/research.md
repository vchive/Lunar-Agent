# Research: Normal-Agent Baseline and Deep-Evolution Boundary

## Verified facts

### Available FM-Eval history

The inspected `famou-bench 1.10.6` experiment used 20 cases, three runs per case, and deep evolution
disabled. Its mean Agent interaction count describes ordinary model/tool turns within each normal
solution attempt. It does not measure outer evolution iterations. The feature therefore consumes a
per-run export for selected cases instead of treating the experiment-wide `0.4712` mean as a
single-case threshold.

The evaluation chain also has separate Answerer/Extractor/Harness roles. Scores must therefore come
through an adapter to the exact frozen extractor/evaluator identity, not Lunar's general model
evaluator and not a number reported by the subject.

### WebAgent source flow

At inspected WebAgent `master` revision `0773e37`:

- `opencode/agents/famou-master.md` delegates normal solving to `famou-build` and then delivers;
- `opencode/commands/evolve.md` activates deep evolution explicitly and says a missing numeric
  argument uses the tool default;
- `opencode/tools/init_evolution.ts` defines `budget.default(5)`;
- `opencode/plugins/evolution-loop.ts` continues while `iteration < budget` and returns to the
  master when complete or budget-exhausted.

Thus source-authoritative no-argument deep evolution is five outer iterations. It is not active in
the available normal experiment.

### Benchmark identity

The current local lite checkout has moved beyond `1.10.6`, so its mutable working tree cannot stand
in for the historical release. FM-Eval's immutable publication, CaseRevision, public projection,
evaluation profile, extractor and evaluator identities must be exported explicitly. Feature 048
refuses to infer these from a branch name or a similar local directory.

## Decisions and alternatives

| Alternative | Decision | Reason |
|---|---|---|
| Re-run all 20 cases × 3 immediately | Defer | Too costly for the first Lunar effect milestone. |
| Compare Lunar loop to the normal WebAgent experiment | Reject | Different treatment: outer evolution versus no outer evolution. |
| Use experiment-wide mean `0.4712` as the target | Reject | It is case-equal aggregate evidence, not a selected-case historical best. |
| Type a remembered best score into CLI | Reject | Cannot prove run provenance, validity, or harness identity. |
| Import WebAgent/FM-Eval code into Lunar | Reject | Breaks standalone/runtime-neutral boundary and is unnecessary for a local adapter. |
| Run one/two cases repeatedly with exact receipts | Select | Affordable, falsifiable first milestone; preserves official scoring identity. |

## Interpretation

“Breakthrough” is a deliberately narrow product milestone: at least one chosen case has complete
planned Lunar coverage and a valid Lunar best strictly above the matching valid WebAgent historical
best. It is useful for deciding whether Lunar has produced a genuinely competitive result on a
real case. It is not suite parity, statistical superiority, or deep-evolution evidence.

The next deep-evolution comparison must generate new matched data: ordinary solution first, then
the same explicit outer-loop budget (initially five, following WebAgent's source default), frozen
harness, model evidence, case and resource envelope for both subjects.
