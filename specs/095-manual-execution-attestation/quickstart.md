# Offline quickstart

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/test_materialization_attestation_store.py tests/test_materialization_attestation.py
.venv/bin/ruff check src tests
.venv/bin/python -m compileall -q src tests
SPECIFY_FEATURE_DIRECTORY="$PWD/specs/095-manual-execution-attestation" \
  bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```
