# Offline quickstart

```sh
.venv/bin/python -m pytest -q tests/test_contract_envelope_prompt_examples.py tests/test_contract_response_framing.py tests/test_conversational.py tests/test_isolated_contract_compiler.py
.venv/bin/python -m pytest -q tests/test_conversational_automatic_bundle.py tests/test_conversational_bundle.py tests/test_conversational_evolution.py tests/test_population_defaults.py tests/test_role_dag_cli.py tests/test_objective_harness_handoff.py
.venv/bin/python specs/112-automatic-bundle-evaluator/quickstart.py
.venv/bin/python tools/run_tests.py --junit-dir .lunar/test-results/feature130
```

The first group parses both literal examples with the production parser and confirms removing the
top-level status still fails. Existing isolation/framing tests verify one request, no tools or prior
history, strict JSON and unchanged malformed-response behavior. The second group and Feature 112
exercise normal contract consumers and terminal multi-file recovery with fresh local fixtures.

These commands make no provider request and do not read or execute Feature 129 captured responses.
They cannot establish real-model adherence or change its frozen 0/1 result.
