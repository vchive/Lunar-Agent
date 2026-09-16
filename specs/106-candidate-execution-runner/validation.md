# Validation

The implementation gate is an offline focused suite covering:

- canonical launch identity stability and deep request/result reconstruction;
- plan, admission, source bundle, staged input, executable, and caller-pin mismatches rejected
  before process creation or input import;
- no-follow roots, disjoint workspace/input inodes, replacement races, changed bytes, and
  bounded input/output handling;
- explicit argv and environment, reserved input namespace, `shell=False`, `DEVNULL` stdin,
  fixed cwd, process-group timeout, descendant cleanup, and reaping;
- success, non-zero exit, signal, timeout, output overflow, start failure, and cleanup failure
  mapped to fixed path-free error codes;
- no Store/home initialization, evaluator/provider/model invocation, Candidate/archive/receipt
  writes, or score/rank side effects;
- installed CLI fixture and a runnable quickstart using only temporary local files.

Required checks after implementation:

```bash
.venv/bin/python -m pytest tests/test_candidate_execution_runner.py \
  tests/test_candidate_execution_runner_files.py \
  tests/test_candidate_execution_runner_cli.py
.venv/bin/ruff check src tests specs/106-candidate-execution-runner
.venv/bin/python -m compileall -q src
.venv/bin/python -m pytest
git diff --check
```

No real model, provider, evaluator, external framework, remote service, or campaign is used for
Feature 106 validation. The feature does not claim parity or algorithmic improvement.
