# Offline verification

Run the focused runtime checks before the shared regression:

```sh
.venv/bin/python -m pytest tests/test_agent_loop.py tests/test_runtime.py tests/test_interactive.py \
  tests/test_agent_evolution.py tests/test_master_planning_role_integration.py
.venv/bin/ruff check src/lunar_evolution/agent_loop.py tests/test_agent_loop.py tests/test_runtime.py
.venv/bin/python -m compileall -q src tests
```

The fixtures use local models and temporary workspaces. They must inspect the captured request
copies and durable transcript rather than relying on provider behavior. A full regression is
required before pushing because `AgentLoopRuntime` is shared by ordinary runs, evolution and
master-planning integrations. This feature does not launch or resume Feature 134.

