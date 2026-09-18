# Offline verification

```sh
.venv/bin/python -m pytest tests/test_evaluator_request_failure.py tests/test_preparation_request_failure.py
.venv/bin/python specs/112-automatic-bundle-evaluator/quickstart.py
.venv/bin/python tools/run_tests.py --junit-dir .lunar/test-results/feature132
```

Fixtures use fresh inputs and synthetic failures, including a local transport timeout. No remote
provider or historical response is replayed. A valid timeout leaves the accepted contract available,
returns a failed preparation with safe request details, and requires explicit resume for a new
attempt. The terminal quickstart still completes with one delivery and no work on repeated resume.
