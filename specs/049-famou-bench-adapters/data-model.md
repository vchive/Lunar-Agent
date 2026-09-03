# Data Model: Executable Famou-Bench Adapters

Feature 049 consumes and emits Feature 048's existing request/receipt/suite/baseline schemas. It
adds no durable database model.

## Provider-observed model turn

```json
{
  "text": "...",
  "tool_calls": [],
  "response_model": "openai/gpt-5.6-sol",
  "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
}
```

The two new fields are optional and backward compatible. Usage is retained only when all three
values are non-negative integers and total equals input plus output.

## Subject adapter output

The existing Feature 048 subject receipt is used. `usage` may be `null` when the provider omitted
telemetry; it is never populated with invented zeroes. `interaction_turns` is always locally
observed. `model_evidence=provider_observed` requires a response model on every turn; otherwise the
configured requested model is reported with `model_evidence=runtime_observed`.

## Harness adapter output

The existing Feature 048 harness receipt is used. Extraction `success` is normalized to
`completed`. Official evaluator extras are not promoted into typed `detail_metrics`; only finite
numeric detail values may appear there.

## Offline results input

Supported containers:

```json
{"meta": {"experiment_id": "fmexp-..."}, "results": []}
```

or:

```json
{"experiment": {"id": "fmexp-..."}, "results": []}
```

Each selected result row must identify `case`; it may use `run_index` or `run_idx`. Readiness is
derived from explicit `projection_state=ready`, or from a legacy completed/scored row with finite
scores. Zero-based indexes are shifted to one-based per case. Duplicate normalized indexes fail.

## Baseline output

The converter emits exactly `TrialBaseline` from Feature 048. Benchmark, evaluation profile, case
revision/digest, and harness hashes are copied from the parsed suite. Runs contain only:

```json
{
  "run_index": 1,
  "ready": true,
  "extraction_status": "completed",
  "validity_score": 1.0,
  "overall_score": 0.8
}
```
