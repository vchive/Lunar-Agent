# Offline quickstart

From the repository root with the existing development environment:

```sh
.venv/bin/python -m pytest -o addopts='' -q \
  tests/test_candidate_response_protocol.py tests/test_candidate_failure_diagnostics.py \
  tests/test_candidate_response_integration.py
```

These fixtures use local scripted model turns and temporary workspaces. They exercise bundle
protocol propagation, unchanged strict parsing and durable failure receipts without any provider
request. Passing them does not establish real model completion or change Feature 139's result.
