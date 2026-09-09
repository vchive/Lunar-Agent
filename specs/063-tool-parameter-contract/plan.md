# Plan: Explicit Tool Parameter Contracts

1. Add failing contract tests for property descriptions and a captured provider request.
2. Add bounded, truthful descriptions at the single `LocalToolRegistry` schema source.
3. Verify the runtime forwards the registry schema without dropping nested descriptions.
4. Run focused and full quality gates, then record the WebAgent v2.5 review and the deferred
   soft-deadline/checkpoint design in `HANDOFF.md`.

## Decisions and alternatives

Use plain JSON Schema descriptions instead of copying WebAgent's OpenCode/Zod workaround. Lunar
does not use Zod or an internal schema registry, so a provider adapter would add complexity without
evidence. Keep descriptions close to the executable schema so a new tool cannot silently acquire a
second, stale documentation table.

## Data model and contract

The existing OpenAI function schema is unchanged except that each property receives a bounded
`description` string. The runtime request body remains the existing JSON object; no new persisted
state or migration is required.

## Complexity tracking

No new dependency, process, persistence field, or provider integration is introduced.

## Local quickstart and evidence boundary

```bash
uv run pytest -o addopts='' -q tests/test_runtime.py tests/test_agent_loop.py \
  tests/test_interactive.py tests/test_memory.py
uv run ruff check src tests
```

The fixture captures the HTTP body sent by a real `AgentLoopRuntime` and `OpenAICompatibleRuntime`
for all four command/memory visibility combinations. It uses a loopback server, no external model,
and no credentials. Existing argument execution tests remain the behavioral authority.

This changes model-visible tool context and may affect token usage and decisions. Future real
evaluation must use a new frozen campaign; the change does not explain or repair old GLM failures.
