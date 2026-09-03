# Implementation Plan: Tool-Capable Evolution Agent Loop

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Summary

Add loop flags to `evolve`, build a fresh `AgentLoopRuntime` around the explicit OpenAI-compatible
runtime for each requested role, include loop settings in runtime provenance, and teach
`RuntimeAgentAdapter` to attach context/transcript paths. No new storage schema is required.

## Decisions

1. **Explicit opt-in** — one-shot runtime remains the default. `--agent-runtime-loop` is only valid
   for `openai-compatible`, where the existing tool-call protocol is available.
2. **Same seam** — loop output is passed through the existing strict bridges; the loop is an
   execution mechanism, not an evaluator authority or new strategy.
3. **Fresh role runtime** — solver and evaluator each receive a separately constructed loop and
   tool registry, avoiding shared conversation/tool state.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Existing standard-library runtime and tools only. |
| Local-First and Durable State | Pass | Candidate workspace transcripts and existing archive. |
| Runtime Adapter Isolation | Pass | RuntimeAgentAdapter remains the only bridge. |
| Artifact-First Verification | Pass | Candidate/evaluator schemas remain authoritative. |
| Bounded Autonomy | Pass | Max steps, no-shell exec opt-in, existing path guards. |
| Recovery | Pass | Fingerprints and detached resume include loop settings. |

