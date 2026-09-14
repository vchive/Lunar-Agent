# Offline quickstart

```sh
.venv/bin/python -m pytest -o addopts='' -q \
  tests/test_materialization_publication.py tests/test_materialization_publication_store.py \
  tests/test_materialization_publication_concurrency.py \
  tests/test_evolved_output_materialization.py tests/test_output_publication.py
```

Interrupted terminal registration should complete from its prepared, validated bytes without
candidate execution. Completed-result drift should still reject without modifying outputs or
database evidence. Legacy results without preparation evidence must never be automatically repaired.

```sh
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/ruff check src tests
.venv/bin/python -m compileall -q src tests
SPECIFY_FEATURE_DIRECTORY="$PWD/specs/089-recoverable-materialization-result" \
  bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```
