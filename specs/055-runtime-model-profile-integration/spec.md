# Feature 055: Runtime Model Profile Integration

## Goal

Apply the provider-neutral `ModelProfile` policy to the local agent loop so token and cost
ceilings are enforced at the runtime boundary while existing callers remain compatible.

## Scope and contract

- `AgentLoopRuntime` accepts an optional `ModelProfile`; omitting it preserves current behavior.
- The profile supplies the default session timeout and caps the configured tool-step limit.
- Each provider usage record is validated and charged through `UsageLedger` before the next tool
  action. Malformed usage and exceeded ceilings fail with a bounded `RuntimeExecutionError` and
  do not charge rejected usage.
- Successful runs expose the credential-free profile name and computed integer `cost_micros` when
  complete usage and prices are available. Existing provider telemetry fields remain unchanged.
- This feature does not discover endpoints, persist credentials, alter evaluator score authority,
  or add a CLI billing workflow.

## Acceptance criteria

1. A profile token ceiling prevents a later model turn from continuing after the ceiling is crossed.
2. A priced profile reports deterministic micro-USD cost telemetry.
3. Runtime construction without a profile behaves exactly as before.
4. Focused and full tests, lint, compilation, build, Specify checks, and diff checks pass.
