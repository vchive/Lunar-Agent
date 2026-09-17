# Offline quickstart

```sh
.venv/bin/python -m pytest -q tests/test_snapshot_request_protocol.py tests/test_evaluator_prompt_protocol.py tests/test_snapshot_evaluator_bundle.py tests/test_candidate_evaluation.py tests/test_source_check_pipeline.py
.venv/bin/python specs/112-automatic-bundle-evaluator/quickstart.py
.venv/bin/python tools/run_tests.py --junit-dir .lunar/test-results
```

The request-protocol fixture uses fresh synthetic data and local processes. It checks target-based
input lookup, paths preserved across nesting, absent optional outputs and zero-byte input metadata.
Compiler and independent auditor retain their existing call counts; terminal resume adds no model,
candidate or delivery activity. The 112 example still selects score 7 from 1/2/6/7.

The full test entry point keeps current tests on current product bytes and runs exactly 24 original
registration tests against their fixed product in a temporary 5560eb9 checkout. It needs local Git
history and records two JUnit reports; either phase failure fails the command. No skip/xfail or
product-guard override is used. Direct unfiltered pytest instead reports product_changed for these
24 fixtures when run on modified product bytes.

No real provider or external framework is called. Do not execute or repair the 123 captured source,
resume an old attempt, or run historical campaign verifiers against modified product bytes.
