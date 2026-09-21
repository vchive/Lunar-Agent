# Validation

## Status

Implementation complete offline as of 2026-09-19. No provider request, campaign resume, evaluator
call, or generated-source execution was performed.

## Required focused checks

- Status reads expose persisted parent, effective, preparation, and recovery fields without Store
  mutation; cancellation, terminal, failed/unknown preparation, and validated preparation obey the
  fixed precedence.
- Runtime/wall retries require matching parent/attempt/input/policy/evidence and recoverability.
  Existing validated interrupted/local/capability/budget continuations retain their resource
  checks. Corrupt or mismatched detail, cancellation, terminal state, and already-prepared state
  create no new preparation request.
- Public transport summaries preserve observed 200 and 4xx/5xx values, keep no-header timeout as
  null, and reject duplicate, unbound, mismatched, invalid, or private transport records.
- Existing diagnostic schemas and status consumers remain compatible. No response body, prompt,
  credential, generated source, or arbitrary exception text crosses the public projection.
- Feature 131/134 retained files and hashes remain unchanged.

The implementation adds stable CLI/JSON status projection fields and aligns the Feature 134
public transport array to the accepted request ledger. Missing optional transport sidecars are
represented as `unavailable` with a null status; only a uniquely bound exchange can expose an
observed HTTP status. The focused recovery/request/wall/capability/local-diagnostics suites passed,
including malformed-stage regression cases, and `tests/test_status_projection.py` passed 4 tests.
No historical guard was changed. The old `tests/test_cli_status.py` reference was corrected to
`tests/test_status_projection.py`.

The independent retained-file inventory matched Feature 131's 21 files/155485 bytes and Feature
134's 97 files/327394 bytes exactly, including all evidence SHA-256 values. No provider was called,
no evaluator or generated source was executed, and no old campaign was resumed.

## Planned commands

```sh
.venv/bin/pytest -q tests/test_preparation* tests/test_measurement* tests/test_status_projection.py
.venv/bin/ruff check src/lunar_evolution/cli.py src/lunar_evolution/automatic_solve_bundle.py \
  specs/134-budgeted-multifile-acceptance/measurement tests
.venv/bin/python -m compileall -q src tests
bash .specify/scripts/bash/check-prerequisites.sh
git diff --check
```

The full current regression completed with `7963 passed, 1 skipped, 24 deselected`; the frozen
Feature 123 stage completed with `24 passed` and no skips. Passing offline tests demonstrates
projection and recovery behavior only; it says nothing about provider latency, model completion,
quality, or WebAgent parity.
