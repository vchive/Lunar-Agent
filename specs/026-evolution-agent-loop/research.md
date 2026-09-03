# Research: Tool-Capable Evolution Agent Loop

`AgentLoopRuntime` already implements bounded OpenAI tool calls, session history, memory, and local
tool safety for normal tasks. The missing integration is construction from `evolve` and context
attachment in `RuntimeAgentAdapter`. Reusing those seams avoids duplicating tool schemas or creating
a second evolution-specific loop.

