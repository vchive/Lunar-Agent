# Offline quickstart

```sh
.venv/bin/python -m pytest -o addopts='' -q \
  tests/test_materialization_delivery.py tests/test_materialization_delivery_store.py \
  tests/test_materialization_delivery_concurrency.py \
  tests/test_evolved_output_materialization.py tests/test_materialization_execution.py \
  tests/test_materialization_publication.py tests/test_output_publication.py
```

Resume with a complete modern execution and no downstream publication can prepare delivery.
Resume after output commit or terminal preparation must finish the original result with one
candidate execution. Verified rollback yields an explicit failed terminal and never republishes.

```sh
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/ruff check src tests
.venv/bin/python -m compileall -q src tests
SPECIFY_FEATURE_DIRECTORY="$PWD/specs/092-recoverable-materialization-delivery" \
  bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```
