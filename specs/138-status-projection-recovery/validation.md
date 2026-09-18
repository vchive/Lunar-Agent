# Validation

## Status

Specification-first as of 2026-09-18. Implementation and tests are intentionally not started in
this step. No provider request, campaign resume, evaluator call, or generated-source execution is
allowed.

## Required focused checks

- Status reads expose persisted parent, effective, preparation, and recovery fields without Store
  mutation; cancellation, terminal, failed/unknown preparation, and validated preparation obey the
  fixed precedence.
- Only recoverable preparation with matching parent/attempt/input/policy/evidence may resume, and
  it creates one new attempt. Corrupt or mismatched detail, cancellation, terminal state, and
  already-prepared state create no request.
- Public transport summaries preserve observed 200 and 4xx/5xx values, keep no-header timeout as
  null, and reject duplicate, unbound, mismatched, invalid, or private transport records.
- Existing diagnostic schemas and status consumers remain compatible. No response body, prompt,
  credential, generated source, or arbitrary exception text crosses the public projection.
- Feature 131/134 retained files and hashes remain unchanged.

## Planned commands

```sh
.venv/bin/pytest -q tests/test_preparation* tests/test_measurement* tests/test_cli_status.py
.venv/bin/ruff check src/famou/cli.py src/famou/automatic_solve_bundle.py \
  specs/134-budgeted-multifile-acceptance/measurement tests
.venv/bin/python -m compileall -q src tests
bash .specify/scripts/bash/check-prerequisites.sh
git diff --check
```

The final validation must include the current full regression and its frozen historical stage,
plus independent Feature 131/134 inventories. Passing offline tests demonstrates projection and
recovery behavior only; it says nothing about provider latency, model completion, quality, or
WebAgent parity.
