# Evaluator Ensemble Contract

The ensemble invokes each explicit evaluator Agent with the normal Feature 016 request and parses
one strict JSON `EvaluationReport`. Aggregation is validity-first:

```text
if every report.validity == 1:
    validity = 1
    combined_score = median(report.combined_score)
else:
    validity = 0
    combined_score = 0
```

Any invocation/parse failure or validity disagreement creates controlled `error_info` and cannot
produce a best candidate. Evaluator workspaces are isolated per member.
