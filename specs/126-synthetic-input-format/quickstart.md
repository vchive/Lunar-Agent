# Offline quickstart

```sh
.venv/bin/python -m pytest -q tests/test_synthetic_input_format.py tests/test_private_data_profile.py tests/test_snapshot_evaluator_bundle.py tests/test_adversarial_evaluator_audit.py tests/test_frozen_evaluator_bundle.py
.venv/bin/python specs/112-automatic-bundle-evaluator/quickstart.py
.venv/bin/python tools/run_tests.py --junit-dir .lunar/test-results
```

Fresh local fixtures demonstrate compiler scalar rejection before any harness or auditor request,
format-valid preparation, and malformed auditor inputs blocking audit execution and freeze. Both
invocation modes check the entire suite before executing its first probe. Existing frozen bundles
retain load-only recovery. The 112 example still selects score 7 from 1/2/6/7 and terminal resume
retains 1/1/1/4/4 contract/compiler/auditor/agent/candidate calls and a single delivery.

The full runner executes current tests on current product and 24 immutable Feature 123 registration
nodes on their fixed historical checkout, including its original pin verification and temporary
test registrations. No live provider request or captured evaluator is run; historical campaign
slots are not reopened.
