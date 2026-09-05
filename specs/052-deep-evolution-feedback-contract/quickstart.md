# Quickstart: Controlled Deep-Evolution Feedback

Run the same deep-trial command as Feature 051 and optionally change the frozen stagnation window:

```bash
lunar-agent effect-deep-trial .lunar/famou-kit/suite.json baseline.json \
  --case-source supply_chain_inventory=.lunar/famou-kit/cases/supply_chain_inventory \
  --subject-command "/absolute/lunar-agent effect-subject --model gpt-5.6-sol --max-steps 100" \
  --harness-command "/absolute/lunar-agent effect-harness --case-root /absolute/private-case" \
  --requested-model gpt-5.6-sol --runs-per-case 2 --outer-rounds 5 \
  --stagnation-rounds 2 --workspace .lunar/deep-effect-trial-002 --json
```

The subject receives the previous round's `previous_evaluation` object. In Feature 052 that name
means the controlled `RoundFeedback` projection, not the private evaluator receipt. The report's
round entries expose only the directive, failure category, and stagnation summary.
