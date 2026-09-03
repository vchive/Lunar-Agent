# Implementation Plan: Execution-Grounded Refinement

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Technical context

`GenerationRequest` already carries complete immutable `Candidate` records and the run workspace.
Each archived candidate points to repository-managed source, while Feature 037 persists sibling
`execution.json` and verified outputs. `AgentCandidateGenerator._prompt` is therefore the narrowest
place to join these records into solver feedback without coupling `LoopStrategy` or
`PopulationStrategy` to a particular Agent runtime.

## Decisions

1. **Prompt-time projection** — read persisted evidence when constructing an Agent request; add no
   new strategy state and make resume naturally use the same source of truth.
2. **One envelope everywhere** — parent, inspirations, and archive entries call the same projector.
3. **Fail-safe degradation** — archive identity and evaluation stay available if source/execution
   evidence is missing or unsafe; the envelope records a stable `unavailable_reason` category.
4. **Metadata, not data** — validated outputs contribute path/size/digest only. Inputs are described
   by the canonical contract and never read into generation context.
5. **Defense in depth** — enforce workspace confinement, reject symlink components, parse execution
   through its value object, redact secrets, and cap source/process excerpts and total prompt size.
6. **Agent seam only** — do not extend `GenerationRequest`; direct callbacks and command generators
   remain byte-for-byte compatible at their boundary.

## Data flow

```text
candidate archive record
        |
        +--> candidate source -- bound/redact/digest --------+
        +--> execution.json -- validate/project ------------+--> refinement envelope
        +--> verified artifacts -- path/size/digest only ---+          |
        +--> EvaluationReport -- bounded data projection ----+          v
                                                         next Agent solver
```

## Recovery and safety

- Prompt reconstruction uses only the supplied run workspace and archive-relative `code_path`.
- Missing, malformed, oversized, escaped, or symlinked evidence yields a stable unavailable marker.
- Candidate-controlled stdout/stderr stay out of the prompt because they can echo raw data; their
  byte counts and the controlled runner error category remain available.
- Prompt size remains subject to `MAX_GENERATION_PROMPT_BYTES`; archive counts stay bounded.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Uses repository-native files and Agent adapter seams. |
| Local-First and Durable State | Pass | Resume reconstructs from local archive/workspaces. |
| Runtime Adapter Isolation | Pass | No strategy or runtime-specific protocol changes. |
| Artifact-First Verification | Pass | Only parsed execution and verified artifact metadata feed refinement. |
| Bounded Autonomy | Pass | Redaction, confinement, size limits, and stable failure categories. |
| Test-First Recovery | Pass | Repair, safety, population, and resume tests precede implementation. |

## Complexity tracking

No dependency, database migration, CLI flag, subprocess protocol, or service is added. The feature
is a bounded evidence projection at the existing Agent generation boundary.
