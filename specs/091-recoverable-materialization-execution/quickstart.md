# Offline quickstart

```sh
.venv/bin/python -m pytest -o addopts='' -q \
  tests/test_materialization_execution.py tests/test_materialization_execution_concurrency.py \
  tests/test_materialization_execution_store.py \
  tests/test_evolved_output_materialization.py tests/test_materialization_launch.py \
  tests/test_materialization_publication.py tests/test_materialization_launch_concurrency.py
```

Only explicitly prepared execution registration may recover. Resume never invokes a candidate or
publishes new outputs. Fully registered execution remains a prerequisite for existing 088/089
recovery; execution registration alone does not supply a missing terminal preparation.

```sh
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/ruff check src tests
.venv/bin/python -m compileall -q src tests
SPECIFY_FEATURE_DIRECTORY="$PWD/specs/091-recoverable-materialization-execution" \
  bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```
