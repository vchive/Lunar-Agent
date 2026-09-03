# Quickstart: Structured Algorithm Outputs

Declare outputs in an algorithm contract:

```json
{
  "outputs": [
    {"path": "output/routes.csv", "format": "csv", "fields": ["item_id", "route_id"]},
    {"path": "output/summary.json", "format": "json", "fields": ["total_distance"]}
  ]
}
```

The Solver runtime writes these paths relative to its private attempt workspace. After the run
succeeds:

```bash
lunar-agent status <run-id> --json
lunar-agent deliver <run-id> --json
```

The status payload lists `kind=output` artifacts. The delivered files are available at
`<run-workspace>/output/routes.csv` and `<run-workspace>/output/summary.json`; use the recorded
SHA-256 values when a parent Agent needs reproducibility.

If a required file is missing or has the wrong format/fields, the task fails and `deliver` remains
ineligible. A contract without `outputs` continues to deliver its legacy result/runtime artifacts.
