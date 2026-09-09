# Plan: Budget-Aware Candidate Preservation

1. Add and observe failures for atomic output, profile deadline propagation, transient hints, and
   one-stream command timeout normalization before implementing their corresponding paths.
2. Add context-local deadline binding to the local registry without changing execute callers.
3. Derive one transient system-context snapshot per profiled model request. Keep isolated and legacy
   no-profile execution behavior compatible.
4. Replace direct `write_file` truncation with a bounded same-directory atomic replacement.
5. Exercise the subject receipt boundary, review implementation, run quality gates, update handoff.

## Decisions and alternatives

Use the existing write tool as the candidate checkpoint surface. A separate checkpoint registry would
duplicate artifacts and introduce ambiguous authority; a file remains an unverified subject product.
Use `ContextVar` plus a scoped context manager for the deadline so synchronous registry subclasses can
keep their execute signature and independent execution contexts do not share a mutable timeout.

Append transient guidance to a copied system message; do not inject it as a user turn or persist it.
The profile already opts into strict accounting. Keep no-profile/isolated prompt behavior compatible.
No fixed ten-second margin: the model/script must choose a soft deadline within the actual cap.

## Data model and contract

No durable schema changes. Budget snapshot version 1 contains numeric/null `remaining_seconds`,
`tool_steps_remaining`, `command_timeout_seconds`, `tokens_remaining`, and `cost_micros_remaining`.
Values represent the instant before the model request, with cumulative allowance based on accepted
prior responses. Deadline scope is internal-only and not a model-controlled argument.

Atomic publication flushes the file before rename; it is not a power-loss or hostile filesystem race
sandbox guarantee. Existing destination permission bits are retained; new files use 0600. Handled
failure cleanup is best effort, and a kill can leave a temp file. Replacing a hard-linked file updates
only that pathname. All successful artifacts continue through independent validation.

## Runnable verification

```bash
uv run pytest -o addopts='' -q tests/test_budget_aware_tools.py tests/test_atomic_tool_output.py \
  tests/test_profile_execution_boundaries.py tests/test_effect_adapters.py
uv run ruff check src tests
```

## Complexity and constitution

No dependencies, service, extra model calls, retries or storage migrations. Existing controller and
private evaluator remain authoritative. Tests cover interruption, failure isolation, and compatibility.
