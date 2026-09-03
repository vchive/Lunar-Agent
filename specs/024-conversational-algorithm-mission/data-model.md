# Data Model: Conversational Algorithm Mission

## CompilationEnvelope

```json
{"status":"compiled","contract":{...}}
```

or:

```json
{"status":"needs_input","questions":[{"question":"What should be minimized?","options":[]}]}
```

Only these top-level keys are accepted (`status` plus `contract` or `questions`). A bounded optional
`assumptions` array is audit text, not an authority override.

## Compiler manifest

`solve/compiler-manifest.json` stores:

```json
{
  "schema_version":"1",
  "status":"compiled",
  "goal_sha256":"…",
  "contract_sha256":"…",
  "plan_id":"plan-…",
  "plan_version":1,
  "runtime_fingerprint":"sha256…",
  "contract_path":"solve/contract.json",
  "plan_path":"solve/plan.json"
}
```

It never stores raw commands, endpoint credentials, or response text.

## Generated task DAG

```text
data_discovery → formulate → solve → verify
```

Each task is represented by the existing `PlanTask`/`Task` rows. The contract is attached to the
plan revision and materialized through the existing algorithm workspace manifest.
