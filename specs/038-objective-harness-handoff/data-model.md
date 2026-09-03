# Data Model: Objective Harness Handoff

No SQLite migration is required.

## Persisted conversational request

```json
{
  "evaluator_command_configured": true
}
```

The marker is stored with ordinary bounded evolution settings. The command is intentionally absent.

## Strategy configuration

`EvolutionConfig.evaluator_fingerprint` remains a 64-character lowercase SHA-256 digest. For an
objective harness it binds the ordered command arguments, adapter kind/name/role, and excludes raw
arguments from `state.json`.

## Harness result

The existing `EvaluationReport` is unchanged. `validity` is checked before quality, and
`combined_score` is always higher-is-better for archive selection even when the domain objective is
a cost to minimize.
