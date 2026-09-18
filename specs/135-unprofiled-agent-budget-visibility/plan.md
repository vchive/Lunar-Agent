# Implementation Plan: Unprofiled Agent-loop budget visibility and completion diagnostics

**Date**: 2026-09-18 | **Spec**: [spec.md](spec.md)

## Technical approach

Keep the change inside `src/famou/agent_loop.py`. Generalize `_budget_messages` to build the
existing request advisory whenever a normal loop has a finite tool-step ceiling, using a nullable
ledger for profile spend fields. Preserve the current JSON keys, guidance text, rounding and
system-message placement. Always return a shallow request copy and copy the system message before
appending guidance. The live `messages` list passed to transcript and next-turn logic remains the
unmodified source.

The loop already computes `remaining` before each request and checks profile time separately. Use
that value for `remaining_seconds`; do not introduce a second clock or a new deadline. Continue to
pass the same timeout to `model.complete`, and keep `run_isolated` on its existing tool-free path.

Introduce a small immutable, repository-owned step-limit evidence value and a typed
`RuntimeExecutionError` subclass in the agent-loop module. At the current whole-batch admission
point, construct evidence from the accepted count and response batch size, emit the existing event
with additive bounded integer fields, then raise the typed error before assistant/transcript append
or tool execution. Keep the existing error string for callers that match it. Subject diagnostics
may continue to classify the event and need no new persistence format.

## Alternatives considered

* Increasing `max_steps` or automatically retrying after an over-limit batch would change execution
  authority and mask the measured failure; both are rejected.
* Mutating the system message in `messages` would make advisory snapshots durable and stale on the
  next request; request-copy injection is required.
* Adding a new profile or ledger for unprofiled runs would incorrectly imply token/cost accounting;
  nullable fields preserve current semantics.
* Executing only the fitting prefix of a tool batch would violate model response atomicity and could
  create partial artifacts; whole-batch rejection remains mandatory.
* Parsing exception prose for structured diagnostics would be unsafe. The typed evidence and event
  payload are produced at the admission boundary from trusted local counters.

## Verification strategy

Add focused tests around `tests/test_agent_loop.py` and `tests/test_runtime.py`, with integration
regressions in `tests/test_interactive.py`, `tests/test_agent_evolution.py` and
`tests/test_master_planning_role_integration.py` as appropriate. Use deterministic fixture models
and a monotonic-clock seam or bounded assertions for decreasing time. Assert provider request
copies, transcript bytes, tool/artifact side effects, event payloads and typed evidence. Confirm
profiled snapshots and isolated calls remain unchanged. Run the focused suites, Ruff, compileall,
Specify prerequisite checks, `git diff --check`, and the repository full regression because this
changes a shared runtime request contract.

## Compatibility and preservation

No CLI, database, model-profile, evaluator-bundle or measurement registration changes are needed.
Existing event consumers receive the same event name and legacy `max_steps`/`tool_steps` fields;
new fields are additive. Feature 134 files remain read-only and are not replayed or regenerated.

