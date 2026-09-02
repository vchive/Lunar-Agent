# Data Model: Agent-Backed Evolution

## `AgentCandidateGenerator`

Configuration consists of an explicit `AgentAdapter`, a safe role, required capabilities, and a
bounded timeout. It implements the existing `CandidateGenerator` callable.

## Agent generation request

The bridge creates an `AgentRequest` with:

- a deterministic local run/task identity derived from the evolution workspace and iteration;
- a prompt containing the algorithm statement/objective, iteration, bounded parent/inspiration
  metadata, and instructions to return candidate source;
- a generation workspace below `evolution/agent/generations/`;
- required capabilities and timeout.

## Candidate result

Successful Agent text becomes `CandidateDraft(source=text)`. A JSON text response may instead contain
`source`, `filename`, and scalar metadata. The strategy then writes the canonical candidate path and
passes it to the independent `CandidateEvaluator`.

No new SQLite table is needed. Existing evolution archive/state JSON and controller events remain the
source of truth.
