# Quickstart: Matched Deep-Evolution Effect Trial

The default is five outer rounds, matching the checked-in WebAgent `/evolve` source behavior when
no numeric argument is supplied:

```bash
lunar-agent effect-deep-trial .lunar/famou-kit/suite.json baseline.json \
  --case-source supply_chain_inventory=/absolute/famou-bench/03_assignment/supply_chain_inventory \
  --subject-command "/absolute/lunar-agent effect-subject --endpoint http://127.0.0.1:11434/v1/chat/completions --model local-model --max-steps 100" \
  --harness-command "/absolute/lunar-agent effect-harness --case-root /absolute/private-case" \
  --requested-model local-model --runs-per-case 2 \
  --workspace .lunar/deep-trial --json
```

The subject is invoked five times per logical run in one attempt workspace. Each later request
contains only the previous round's validity/quality/overall score summary. The independent harness
scores every round; `report.json` contains `round_curve`, `score_p50`, `score_p90`, `quality_p50`,
and `quality_p90`. Use `--resume` after an interruption.

The case report also contains `failure_statistics` with run and round error-code counts,
feedback failure categories, timeout totals, and a deterministic per-round recorded/completed
ledger. It is diagnostic metadata derived from validated receipts and does not act as a scoring
source.

This is a descriptive one/two-case effect check. It does not claim WebAgent prompt/role identity,
full-suite parity, or a statistically powered superiority result.
