# Recovery Proposal CLI and JSON Contract

```bash
lunar-agent recover <run-id> --json
```

The command is advisory and exits `0` for an existing run regardless of its execution status. A
missing run is an error. It never starts or changes work.

Example acceptance failure proposal:

```json
{
  "run_id": "run-123",
  "status": "failed",
  "proposal": {
    "schema_version": "1",
    "action": "propose_patch",
    "run_id": "run-123",
    "run_status": "failed",
    "plan_id": "report-plan",
    "plan_version": 1,
    "task_id": "run-123-report",
    "plan_task_id": "report",
    "rationale": "Independent acceptance verification failed for a planned task.",
    "evidence": ["run_status:failed", "task_state:failed", "evaluation:failed", "acceptance:artifact_exists"],
    "questions": [],
    "guidance": {"required_operation": "update_task", "target": "report", "inspect": ["evaluation"]},
    "fingerprint": "<sha256>",
    "artifact_path": "recovery/proposals/<sha256>.json"
  }
}
```

After this call, `lunar-agent status <run-id> --json` includes the same proposal object at
`recovery`. Existing status fields are unchanged.
