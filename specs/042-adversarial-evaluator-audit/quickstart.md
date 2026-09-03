# Quickstart: Adversarial Evaluator Audit

Use the existing compiled-evaluator mode:

```bash
lunar-agent solve "minimize route cost and write output/routes.csv" \
  --input ./orders.csv --runtime openai-compatible \
  --endpoint http://127.0.0.1:11434/v1 --model local-model \
  --evolve --compile-evaluator --strategy population --json --home .lunar
```

Lunar-Agent first compiles and self-tests the evaluator, then starts a fresh auditor turn that sees
the evaluator but not its self probes. Search starts only if both independently generated suites
pass. The frozen bundle contains read-only `probes.json` and `audit.json`; resume validates both and
makes no compiler or auditor call.

The deterministic repository scenario is:

```bash
uv run pytest -q tests/test_adversarial_evaluator_audit.py tests/test_frozen_evaluator_bundle.py
```
