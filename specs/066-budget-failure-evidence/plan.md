# Plan: Budget Failure Evidence

1. Add failure-first tests for token/cost overshoot, exact tool exhaustion, schema compatibility,
   malformed/oversized evidence, and normal/deep failure authority.
2. Capture immutable accepted and observed snapshots inside the profile ledger before ceiling checks.
   A profile-specific BudgetExceeded subtype transports those snapshots without changing the ledger
   commit rule or the controller's generic BudgetExceeded.
3. Wrap that evidence in a dedicated RuntimeExecutionError subtype at the agent loop boundary, also
   used for exact tool exhaustion. Project only this exact type, never arbitrary attributes or text.
4. Emit v2 only for typed budget failures; keep all other failures v1. Accept both versions strictly,
   verify available arithmetic and state relationships, and collect without upgrading old sidecars.
5. Review, run focused/full checks, update the handoff, commit and push the authorized main branch.

## Data model and contracts

V2 has exactly the existing v1 fields plus `budget`. Its classification is runtime/budget_exceeded
with null http_status. The budget object has exactly:

- `limit`: max_total_tokens or max_cost_micros; `state`: exceeded or exhausted.
- `maximum`: positive bounded integer or null when outside the diagnostic cap.
- `accepted_usage`, `observed_usage`: UsageSnapshot objects or null when not safely representable.
  Each snapshot contains input_tokens, output_tokens, total_tokens, cost_micros (nullable without
  configured prices), and rounds. Observed includes the trigger; accepted is the ledger at failure.
- `trigger_recorded`: false for exceeded, true for exhausted.
- `usage_completeness`: the fixed string partial.

For available snapshots validate totals, cost availability, monotonicity and rounds. Exhausted
snapshots must agree; exceeded observed rounds are accepted rounds + 1. Available selected values
must match the declared > or == maximum relationship; accepted values cannot exceed it. A null
snapshot is unknown/unrepresentable, not a zero reading. model_turns/tool_steps remain emitted
event counters, so the triggering response is not added retroactively.

## Decisions and alternatives

Typed exceptions retain failure-local data without adding mutable observer caches or changing event
order. Do not parse BudgetExceeded prose or project arbitrary exceptions' fields. Keep nested v2
schema rather than adding optional fields to strict v1. Do not expand diagnostics to all failure
usage: timeout and missing/invalid usage require different observability contracts.

Old readers may decline v2 claims, preserving the original process error. No persisted state or
receipt migration is needed. Historical manifests and summaries are immutable; their source-hash
checks naturally refer to the previous implementation and must not be rewritten for this feature.

## Runnable verification

```bash
uv run pytest -o addopts='' -q tests/test_budget_failure_evidence.py tests/test_subject_diagnostics.py \
  tests/test_profile_execution_boundaries.py tests/test_effect_adapters.py \
  tests/test_effect_trial.py tests/test_deep_effect_trial.py
uv run ruff check src tests
```

Then full pytest, compileall, build, Specify prerequisites and git diff --check. All model fixtures
are deterministic or local HTTP servers. No dependency or service changes; authority remains with
the controller/private evaluator. No constitution exception.
