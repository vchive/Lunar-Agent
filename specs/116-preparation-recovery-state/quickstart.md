# Offline quickstart

From the repository root with its bootstrapped virtual environment:

```sh
.venv/bin/python -m pytest -q tests/test_store_input_waiting.py tests/test_preparation_recovery.py tests/test_preparation_recovery_cli.py
.venv/bin/python -m pytest -q tests/test_interactive.py tests/test_store.py tests/test_automatic_solve_bundle.py tests/test_conversational_automatic_bundle.py
.venv/bin/python specs/112-automatic-bundle-evaluator/quickstart.py
bash .specify/scripts/bash/check-prerequisites.sh --json
```

The fixture runtime uses no provider credentials or network. The existing executable quickstart
must still deliver independent scores 1, 2, 6, 7, retain one delivery and reuse terminal evidence
without additional contract/compiler/auditor/generator/candidate invocations. Recovery tests
exercise compiler/auditor failures, status inspection, stray answer rejection, explicit resume,
retained contract bytes and terminal idempotency. CLI failure JSON contains the same parent ID,
`status="failed"`, `run_status="running"`, `input_request=null`, and
`evolution.preparation.status="failed"`. An explicit successful fixture resume changes preparation
to `prepared`, delivers the candidate and creates no extra calls when resumed again.
