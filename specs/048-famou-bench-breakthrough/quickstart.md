# Quickstart: Small Famou-Bench Breakthrough Trial

First export the selected cases' exact `famou-bench 1.10.6` identities/public ledgers and FM-Eval
per-run WebAgent receipts into `suite.json` and `baseline.json`. Do not manually enter a best score.
Explicit adapter evidence in the FM-Eval export must consistently identify `webagent`; AgentServer
or conflicting evidence is rejected before the baseline is written.

Run one or two cases three times each in ordinary Agent mode:

```bash
lunar-agent effect-trial suite.json baseline.json \
  --case-source logistics_vehicle_dispatch_scheduling=/absolute/case/root \
  --subject-command "/absolute/lunar-famou-subject" \
  --harness-command "/absolute/famou-harness-adapter" \
  --requested-model gpt-5.6-sol \
  --runs-per-case 3 --timeout 3600 \
  --workspace .lunar/effect-trial-001 --json
```

Resume an interrupted run with the same frozen inputs and options plus `--resume`. Completed logical
runs are reused only when runner-owned state already registers their exact record digest.

An achieved milestone means at least one selected case had full planned Lunar coverage and a valid
Lunar best score strictly above the matching exported WebAgent historical best. It does not mean
20-case parity or formal superiority. Deep evolution is not part of this command; WebAgent source
uses five outer iterations when `/evolve` is invoked without a numeric budget.

Deterministic repository checks:

```bash
uv run pytest -q tests/test_effect_trial.py tests/test_cli.py
uv run pytest -q
uv run ruff check .
```
