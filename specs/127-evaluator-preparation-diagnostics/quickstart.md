# Offline quickstart

```sh
.venv/bin/python -m pytest -q tests/test_evaluator_preparation_diagnostics.py tests/test_preparation_local_diagnostics.py tests/test_preparation_recovery.py tests/test_preparation_recovery_cli.py
.venv/bin/python specs/112-automatic-bundle-evaluator/quickstart.py
.venv/bin/python tools/run_tests.py --junit-dir .lunar/test-results/feature127
```

Fresh malformed synthetic inputs and evaluator responses produce typed local failures without
freezing a bundle or starting candidate work. Automatic solve retains only bounded enum/index
details in its failed event, visible through normal status. Invalid detail cannot authorize recovery.
The successful 112 example must still choose score 7 and terminal resume adds no calls or delivery.

For example, a malformed second input in the third compiler probe is represented as:

```json
{
  "schema_version": "1",
  "stage": "compiler_preflight",
  "reason": "input_format_invalid",
  "probe_index": 3,
  "input_index": 2,
  "order_index": null
}
```

This is the `local_failure` value inside a schema 2 failed preparation observation. Text status
also prints `preparation_local_failure: input_format_invalid probe_index=3 input_index=2`.
The example is illustrative, not a real measurement outcome. An auditor validity mismatch is
`auditor_preflight`/`validity_mismatch` with only probe_index; failure to parse either response
is `compiler_response` or `auditor_response`/`response_invalid` with all indices null.

Full regression runs current tests on current product and 24 unchanged historical registration
nodes on their fixed checkout. It verifies original pins and disposable test registrations without
reopening an original campaign or requesting a real provider.
