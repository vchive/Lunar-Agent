# Feature 054: Model Profiles and Cost Control

## Goal

Make model selection and per-run spend limits explicit and locally verifiable. Runtime adapters
currently expose normalized token usage as telemetry, but callers have no shared policy object for
model identity, thinking budget, step/time limits, or token/cost ceilings.

## Scope

- Add a provider-neutral `ModelProfile` with bounded model id, thinking budget, max steps, timeout,
  optional total-token ceiling, and optional micro-USD token prices/cost ceiling.
- Add a pure `UsageLedger` that accepts normalized runtime usage, aggregates per-round tokens, and
  rejects malformed samples or samples crossing a configured ceiling before mutating state.
- Expose immutable snapshots suitable for effect-trial/runtime telemetry. No credentials, endpoint
  discovery, billing calls, or changes to score authority are included.

## Contract

`ModelProfile.to_dict()` is JSON-safe and round-trips through `from_dict()`. Model ids and names are
bounded credential-free text. `thinking_budget` is 0..1,000,000; `max_steps` is 1..200;
`timeout_seconds` is finite and <= 86,400. Ceilings and prices are non-negative integers, with zero
ceilings rejected and input/output prices required as a pair.

`UsageLedger.record()` requires exactly `input_tokens`, `output_tokens`, and `total_tokens` as
non-negative integers whose sum is consistent. It raises `BudgetExceeded` for token or cost limits
without charging the rejected sample. Costs are integer micro-USD and round each token direction up
to the nearest 1,000-token unit; absent prices, `cost_micros` is null.
