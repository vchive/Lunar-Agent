# Offline quickstart

```sh
.venv/bin/python -m pytest -o addopts='' -q \
  tests/test_materialization_launch.py tests/test_materialization_launch_concurrency.py \
  tests/test_materialization_launch_durability.py tests/test_materialization_launch_store.py \
  tests/test_evolved_output_materialization.py tests/test_materialization_publication.py \
  tests/test_materialization_publication_concurrency.py
```

An interrupted authorized launch must preserve its attempt and reject automatic reexecution.
A competing process must fail promptly while the lifecycle lock is held. Completed results and
explicitly prepared terminal publications remain reusable after launch evidence validation.

```sh
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/ruff check src tests
.venv/bin/python -m compileall -q src tests
SPECIFY_FEATURE_DIRECTORY="$PWD/specs/090-durable-materialization-launch" \
  bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```
