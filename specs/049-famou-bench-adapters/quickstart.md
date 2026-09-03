# Quickstart: Built-in Famou-Bench Adapters

Convert an authorized local FM-Eval results response. Immutable publication/case/harness identity
comes from a separately exported frozen suite:

```bash
lunar-agent effect-baseline results.json suite.json baseline.json \
  --experiment-id fmexp-... \
  --requested-model gpt-5.6-sol \
  --effective-model openai/gpt-5.6-sol \
  --model-evidence not_observable --json
```

Run Feature 048 with Lunar's built-in normal subject and exact private harness. The historical
`1.10.6` case root and an environment containing that case extractor's dependencies are external
owner inputs; they are not bundled in Lunar:

```bash
lunar-agent effect-trial suite.json baseline.json \
  --case-source case-a=/absolute/public-case-projection \
  --subject-command "/absolute/lunar-agent effect-subject --model gpt-5.6-sol --max-steps 100" \
  --subject-env FAMOU_MODEL_ENDPOINT --subject-env FAMOU_API_KEY \
  --harness-command "/absolute/lunar-agent effect-harness --case-root /absolute/private-case --extractor-env ANTHROPIC_AUTH_TOKEN --extractor-env ANTHROPIC_BASE_URL" \
  --harness-env ANTHROPIC_AUTH_TOKEN --harness-env ANTHROPIC_BASE_URL \
  --requested-model gpt-5.6-sol --runs-per-case 3 --timeout 3600 \
  --workspace .lunar/effect-trial-001 --json
```

The effect runner appends its generated request path to each built-in command. It still owns
repetition, recovery, strict comparison, and the deliberately narrow single-case milestone.

Deterministic repository checks:

```bash
uv run pytest -q tests/test_effect_adapters.py tests/test_effect_trial.py tests/test_runtime.py
uv run pytest -q
uv run ruff check .
```
