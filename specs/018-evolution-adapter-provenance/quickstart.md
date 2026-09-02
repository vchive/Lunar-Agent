# Quickstart: Resume with Adapter Provenance

Use explicit commands for a detached run:

```bash
lunar-agent evolve contract.json --strategy loop --detach \
  --generator-command "/absolute/path/to/generator-wrapper" \
  --evaluator-command "/absolute/path/to/evaluator-wrapper" \
  --json --home .lunar
```

Resume with the same command/profile options. Lunar-Agent stores only SHA-256 fingerprints in
`evolution/state.json`; changing a command, role, name, or required capability is rejected before
the task is claimed.

Callback-based library callers may omit both fingerprints. OpenEvolve continues to use its existing
explicit command digest.
