# Validation

Implemented and validated offline on 2026-09-16. The 34 API, 49 filesystem and 13 CLI cases pass
(96 total), including the installed CLI and source/destination/interruption scenarios. The runnable
quickstart, Ruff, compileall and diff checks pass. Final full regression passes **4568 tests with
one existing skip in 235.87s**, including the additional Feature 103 constructor-error compatibility
test. Frozen Feature 051/074/076/078/082 files are unchanged from `85d7f4c`.
No new effect measurement is claimed.

Validation commands (from the repository root):

```bash
.venv/bin/python -m pytest tests/test_candidate_input_staging.py \
  tests/test_candidate_input_staging_files.py tests/test_candidate_input_staging_cli.py
.venv/bin/python specs/105-candidate-input-staging/quickstart.py
.venv/bin/ruff check src tests specs/105-candidate-input-staging/quickstart.py
.venv/bin/python -m compileall -q src
.venv/bin/python -m pytest
git diff --check
```

Coverage:

- Focused API and filesystem tests for fresh admission replay, copies, destination readback,
  directory identity aliases, failure/interruption cleanup, and bounded error messages.
- Installed CLI fixture demonstrating binary input copies with no runner or home/Store effects.
- Runnable quickstart, full repository regression, Ruff, compileall, and `git diff --check`.

No real model, provider, framework, remote service, campaign, or effect evaluator is used for
Feature 105 validation. Existing offline repository fixtures may run their own local test commands.
