# Quickstart: Explicit Local Agent Delegation

The base installation is standalone; no Hermes, OpenCode, OpenClaw, or Codex installation is
required. A worker is supplied explicitly as an absolute executable.

```bash
uv run lunar-agent delegate "inspect the repository and summarize the failing tests" \
  --agent-command "/absolute/path/to/my-agent-wrapper" \
  --agent-role solver \
  --capability read_files \
  --capability write_artifacts \
  --json
```

The wrapper receives one JSON object on stdin and must emit one JSON object on stdout:

```json
{
  "run_id": "...",
  "task_id": "...",
  "role": "solver",
  "prompt": "...",
  "workspace": "/absolute/run/workspace/tasks/...",
  "timeout": 900
}
```

The response may be structured:

```json
{
  "status": "succeeded",
  "text": "...",
  "artifacts": ["answer.md"],
  "metadata": {"provider": "my-agent"}
}
```

or bounded plain text. `answer.md` must be created below the supplied workspace. Lunar-Agent
records and hashes it, evaluates the returned text, and settles the task in SQLite. A worker result
alone cannot mark a run successful.

For library callers, construct an `AgentRegistry`, register a `RuntimeAgentAdapter` or
`CommandAgentAdapter`, and call `LocalController.run_agent(...)`. The registry never searches PATH,
home directories, or remote services.
