# Offline verification

Feature 136 is specification-first. After implementation, run the deterministic candidate-budget
fixtures before the shared regression:

```sh
.venv/bin/python -m pytest tests/test_agent_candidate_generation_budget.py \
  tests/test_agent_loop.py tests/test_agent_evolution.py tests/test_agent_bundle_generation.py
.venv/bin/ruff check src/famou/agent_loop.py src/famou/agents.py \
  src/famou/agent_evolution.py src/famou/agent_bundle_generation.py \
  tests/test_agent_candidate_generation_budget.py
.venv/bin/python -m compileall -q src tests
```

The fixtures should use local scripted model turns and temporary workspaces. Inspect captured
request copies, event payloads, candidate records, and transcript bytes directly. The canonical
`4 + 2` case must show whole-batch rejection and zero side effects from the rejected batch. The
success case must include a final nonempty tool-free response accepted by the native parser.

Then run the repository's two-stage regression and Specify checks from [validation.md](validation.md).
This quickstart never launches or resumes Feature 134 and does not call a real provider.
