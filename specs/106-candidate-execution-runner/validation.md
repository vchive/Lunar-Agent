# Validation

The offline focused suite exercises:

- successful execution with the staged input namespace, workspace cwd, and relative root paths;
- caller plan/admission/bundle/contract pin rejection before process creation and rechecking changed
  source/input bytes;
- symlink and FIFO root rejection, disjoint workspace/input roots, reserved environment rejection,
  and the supported process budget;
- acceptance of all 32 planned command items and rejection of unsafe executable paths;
- executable file/ancestor/mode changes, final root replacement, and descriptor closure on rejection;
- non-zero exit, timeout (including declarations below 0.05 seconds), background descendants
  holding pipes, output overflow, and fixed
  process-start failure telemetry;
- output-text omission from serialized results, CLI path-free metadata, and no normal config/home
  initialization;
- an installed CLI fixture using temporary local files.

Feature 106's focused suite passed all 32 tests after the executable preflight, command-boundary,
timeout-budget and CLI-pin corrections. Ruff, compileall and `git diff --check` passed for these
changes. The final combined repository regression with Feature 107 passed **4707 tests,
1 skipped in 232.92 seconds**, with zero JUnit failures or errors.

Required checks after implementation:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_candidate_execution_runner.py \
  tests/test_candidate_execution_runner_files.py \
  tests/test_candidate_execution_runner_cli.py
.venv/bin/ruff check src tests specs/106-candidate-execution-runner
.venv/bin/python -m compileall -q src
PYTHONPATH=. .venv/bin/python -m pytest
git diff --check
```

No real model, provider, evaluator, external framework, remote service, or campaign is used for
Feature 106 validation. The feature does not claim parity or algorithmic improvement.
