# Offline quickstart

```sh
lunar-agent diagnose-materialization PARENT_RUN_ID EVOLUTION_RUN_ID --home .lunar --json
.venv/bin/python -m pytest -o addopts='' -q tests/test_diagnostic_snapshot.py tests/test_materialization_diagnostics.py
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/ruff check src tests
.venv/bin/python -m compileall -q src tests
SPECIFY_FEATURE_DIRECTORY="$PWD/specs/093-readonly-materialization-diagnostics" \
  bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```

The command prints observations and retains source evidence. A report is not recovery
authorization; existing resume performs the normal protocol and acceptance checks.
