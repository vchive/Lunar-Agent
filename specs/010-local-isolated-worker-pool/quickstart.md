# Quickstart: Local Isolated Worker Pool

The default remains serial and requires no factory:

```bash
lunar-agent run "write a local report" --runtime mock --home .lunar --json
```

For independent plan tasks, request local parallelism. The repository CLI constructs a fresh
runtime adapter for every task:

```bash
lunar-agent run --plan plan.json --runtime mock --workers 2 --home .lunar --json
lunar-agent resume <run-id> --runtime mock --workers 2 --home .lunar --json
```

The JSON run handle includes `workers`. Dependencies still execute in DAG order; only currently
ready tasks overlap. Cancellation and recovery remain the existing `cancel` and `recover` commands.
