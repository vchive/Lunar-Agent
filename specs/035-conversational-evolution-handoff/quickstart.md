# Quickstart: Conversational Evolution Handoff

Run a deterministic local smoke mission:

```bash
lunar-evolution solve "optimize a routing algorithm" \
  --runtime mock --evolve --strategy loop --max-rounds 2 \
  --json --home .lunar
```

The response contains the intake `run_id` and linked `evolution_run_id`. Inspect either ledger:

```bash
lunar-evolution status <run-id> --json
lunar-evolution status <evolution-run-id> --json
```

For a long run, add `--detach`. The returned intake ID is stable; the child evolution ID appears
after compilation and is also recorded in the intake `evolution_linked` event.
