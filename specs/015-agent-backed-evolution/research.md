# Research Notes: Agent-Backed Evolution

## Existing seams

Feature 013's `GenerationRequest` already carries iteration, parent, inspirations, archive, and
workspace. `CandidateDraft` and `EvaluationReport` provide bounded source and validity-first
contracts. Feature 014's `AgentRequest`/`AgentResult` and `CommandAgentAdapter` provide explicit
role/capability selection and JSON subprocess handling.

## Decisions

1. Put the bridge in `agent_evolution.py`, not in the strategy module. Evolution strategies remain
   independent of Agent protocols and can still be used with pure callbacks or command adapters.
2. `AgentCandidateGenerator` sends a bounded planning prompt and converts successful text to a
   `CandidateDraft`; a JSON `{source, filename, metadata}` response is also accepted.
3. The bridge uses a dedicated `evolution/agent/generations/<iteration>/` directory below the run
   workspace. It never grants a worker a Store handle or a path outside the run.
4. The evaluator remains a separate callback/command. Agent-generated source is persisted and
   evaluated by the existing validity-first archive logic.
5. The CLI's `--agent-command` is mutually exclusive with `--generator-command`; this avoids
   ambiguous duplicate solver calls. `--agent-capability` values are required capabilities, while
   the adapter declares the canonical local capability set by default.

## Alternatives rejected

- Embedding Agent invocation into `LoopStrategy`/`PopulationStrategy`: would couple search state to
  a specific runtime and make pure deterministic tests harder.
- Letting an Agent return an evaluation report as proof: violates independent verification.
- Persisting full archive source in every Agent prompt: unbounded context growth and secret leakage.
