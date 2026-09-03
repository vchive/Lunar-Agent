# Data Model: Frozen Famou-Bench Breakthrough Trial

## Suite manifest

```json
{
  "schema_version": "1",
  "benchmark": {
    "name": "famou-bench",
    "release_version": "1.10.6",
    "publication_digest": "sha256:<64hex>"
  },
  "evaluation_profile": {
    "name": "famou-agentco-default",
    "revision": 1,
    "digest": "sha256:<64hex>"
  },
  "cases": [{
    "key": "logistics_vehicle_dispatch_scheduling",
    "revision_id": "<immutable CaseRevision id>",
    "digest": "sha256:<64hex>",
    "entrypoint": "instruction.md",
    "public_files": [
      {"path": "instruction.md", "size": 123, "sha256": "<64hex>"},
      {"path": "data/data.xlsx", "size": 456, "sha256": "<64hex>"}
    ],
    "harness": {
      "extractor_sha256": "<64hex>",
      "evaluator_sha256": "<64hex>"
    }
  }]
}
```

Only one or two cases are accepted. `public_files` is an ordered, exact copy ledger. Private names
(`gt.json`, `tests/**`, `.harness/**`, evaluator/extractor source) are never valid ledger entries.

## Baseline export

```json
{
  "schema_version": "1",
  "source": "fm-eval",
  "experiment_id": "fmexp-...",
  "authority": "descriptive",
  "conclusion_eligibility": "ineligible",
  "benchmark": {"name": "famou-bench", "release_version": "1.10.6", "publication_digest": "sha256:<64hex>"},
  "evaluation_profile": {"name": "famou-agentco-default", "revision": 1, "digest": "sha256:<64hex>"},
  "model": {"requested": "gpt-5.6-sol", "effective": "openai/gpt-5.6-sol", "evidence": "not_observable"},
  "cases": [{
    "key": "logistics_vehicle_dispatch_scheduling",
    "revision_id": "<immutable CaseRevision id>",
    "digest": "sha256:<64hex>",
    "harness": {"extractor_sha256": "<64hex>", "evaluator_sha256": "<64hex>"},
    "runs": [
      {"run_index": 1, "ready": true, "extraction_status": "completed", "validity_score": 1.0, "overall_score": 0.80}
    ]
  }]
}
```

No `best_score` field is accepted. Lunar derives it from valid per-run receipts.

## Subject receipt

```json
{
  "schema_version": "1",
  "mode": "normal",
  "status": "completed",
  "requested_model": "gpt-5.6-sol",
  "effective_model": "openai/gpt-5.6-sol",
  "model_evidence": "runtime_observed",
  "interaction_turns": 42,
  "usage": {"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200}
}
```

The receipt has no score field. Unsupported keys are rejected.

## Harness receipt

```json
{
  "schema_version": "1",
  "status": "completed",
  "benchmark": {"name": "famou-bench", "release_version": "1.10.6", "publication_digest": "sha256:<64hex>"},
  "evaluation_profile": {"name": "famou-agentco-default", "revision": 1, "digest": "sha256:<64hex>"},
  "case": {"key": "logistics_vehicle_dispatch_scheduling", "revision_id": "<id>", "digest": "sha256:<64hex>"},
  "harness": {"extractor_sha256": "<64hex>", "evaluator_sha256": "<64hex>"},
  "extraction_status": "completed",
  "validity_score": 1.0,
  "overall_score": 0.81,
  "quality_score": 0.81,
  "detail_metrics": {}
}
```

## Trial report

```json
{
  "schema_version": "1",
  "protocol": "famou-bench-breakthrough-v1",
  "mode": "normal",
  "suite_sha256": "<64hex>",
  "baseline_sha256": "<64hex>",
  "baseline": {
    "source": "fm-eval",
    "experiment_id": "fmexp-...",
    "authority": "descriptive",
    "model": {"requested": "gpt-5.6-sol", "effective": "openai/gpt-5.6-sol", "evidence": "not_observable"}
  },
  "config": {
    "runs_per_case": 3,
    "timeout_seconds": 3600.0,
    "requested_model": "gpt-5.6-sol",
    "subject_command_sha256": "<64hex>",
    "harness_command_sha256": "<64hex>",
    "subject_env_names": [],
    "harness_env_names": []
  },
  "cases": [{
    "key": "logistics_vehicle_dispatch_scheduling",
    "revision_id": "<immutable CaseRevision id>",
    "digest": "sha256:<64hex>",
    "harness": {"extractor_sha256": "<64hex>", "evaluator_sha256": "<64hex>"},
    "planned_runs": 3,
    "ready_runs": 3,
    "valid_runs": 2,
    "valid_rate": 0.6666666667,
    "lunar_best": 0.81,
    "webagent_historical_best": 0.80,
    "score_delta": 0.01,
    "score_breakthrough": true,
    "milestone_achieved": true,
    "runs": []
  }],
  "milestone": {"achieved": true, "case_keys": ["logistics_vehicle_dispatch_scheduling"]},
  "comparability": {
    "kind": "descriptive_same_frozen_harness",
    "model_identity_evidence": "not_provider_observed",
    "formal_conclusion_eligibility": "ineligible",
    "baseline_conclusion_eligibility": "ineligible",
    "limitations": [
      "selected_cases_do_not_establish_suite_parity",
      "best_of_n_is_not_a_statistical_superiority_test",
      "normal_mode_does_not_measure_deep_evolution",
      "process_capability_separation_is_not_an_os_sandbox"
    ]
  }
}
```

Commands, environment values, stdout/stderr, absolute paths, baseline receipts, and private harness
configuration are excluded from `report.json`.
