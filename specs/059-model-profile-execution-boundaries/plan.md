# Plan: Model Profile Execution Boundaries

## Implementation

1. Add regression tests before implementation using scripted ModelTurns, fake clocks, real local
   write-file tools and temporary transcripts. Verify that forbidden actions never occur.
2. Factor profile timeout selection and response usage validation into small shared helpers in
   `agent_loop.py`. Keep UsageLedger's deterministic accepted-sample semantics unchanged.
3. Use invocation-local ledgers in normal and isolated paths. Enforce remaining deadlines at
   action boundaries and require usage only when a spend ceiling exists.
4. Reject exact-ceiling tool continuations while allowing terminal equality. Keep ordinary
   metadata compatible; add profile telemetry to isolated results only with a profile.
5. Add subject adapter regression evidence, update README/HANDOFF and complete validation.

## Verification

Run new regression tests red first, then focused loop/model-profile/adapter/audit tests. Run
`uv run pytest -q`, `uv run ruff check src tests`, `uv run python -m compileall -q src`, `uv build`,
Feature 059 Specify prerequisites and `git diff --check` after implementation.
Only deterministic local fixtures are executed; no external model or private harness is called.
