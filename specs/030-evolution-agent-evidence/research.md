# Research: Evolution Agent Evidence

`RuntimeAgentAdapter` already adds `session-transcript.jsonl` to an `AgentResult`, but
`AgentCandidateGenerator` and `AgentCandidateEvaluator` only consume `result.text`. The existing
`AgentLoopRuntime` emits bounded `agent_model_turn`, `agent_tool_result`, and step-limit events,
and the normal task controller wires its event sink. Evolution uses a separate observer hook, so
the missing connection is an optional bridge observer rather than a new event system.

The existing `ArtifactStore.record` computes SHA-256 and enforces run confinement. Evolution bridge
validation must happen before that call and reject symlink components because `Path.resolve()` alone
would otherwise make a symlinked file look safely relative. SQLite artifact rows are intentionally
not deduplicated globally; controller-side path/kind checks provide resume idempotency.
