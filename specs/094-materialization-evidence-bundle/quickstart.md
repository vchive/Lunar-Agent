# Offline quickstart

```sh
lunar-agent export-materialization-evidence PARENT CHILD --home .lunar --output ./evidence.json --json
.venv/bin/python -m pytest -o addopts='' -q tests/test_materialization_evidence_bundle.py
.venv/bin/ruff check src tests
.venv/bin/python -m compileall -q src tests
SPECIFY_FEATURE_DIRECTORY="$PWD/specs/094-materialization-evidence-bundle" \
  bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```
