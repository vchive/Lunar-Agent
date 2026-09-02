# Quickstart: Evidence-Guided Recovery

This uses the local mock runtime and requires no model, Hermes, network, or global agent setup.

```bash
state_dir=$(mktemp -d)
cat > "$state_dir/plan.json" <<'JSON'
{
  "goal": "write a verified report",
  "plan_id": "quickstart-recovery",
  "tasks": [{
    "id": "report",
    "title": "Report",
    "prompt": "Write report.json",
    "acceptance": {"artifact_exists": "report.json"}
  }]
}
JSON

lunar-agent plan "$state_dir/plan.json" --runtime mock --home "$state_dir/home" --json
# The mock result does not create report.json, so this plan exits non-zero after emitting its run ID.

lunar-agent recover <run-id> --home "$state_dir/home" --json
lunar-agent status <run-id> --home "$state_dir/home" --json
```

`recover` recommends `propose_patch` and persists `recovery/proposals/<fingerprint>.json`; it does
not edit the plan. Inspect the status evaluation, then submit a deliberate `patch`/`replan` and run
the existing `resume` command with the intended runtime.
