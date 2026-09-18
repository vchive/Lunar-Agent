# Implementation Plan: Candidate-stage explicit tool budget and completion diagnostics

**Date**: 2026-09-18
**Spec**: [spec.md](spec.md)

## Technical approach

1. Trace the native and bundle generation paths from `AgentCandidateGenerator` and
   `generate_bundle_candidate` through `AgentRequest`, `RuntimeAgentAdapter`, and
   `AgentLoopRuntime`. Keep deterministic callback and command-generator paths unchanged.
2. Introduce the smallest immutable candidate-budget value at the generator boundary. Validate a
   positive bounded integer before creating a generation workspace or invoking an adapter. Derive
   a canonical budget identity from the owning run/task, generation ordinal, and effective budget;
   pass it as authority-bound request/runtime context rather than accepting it from model output.
3. Reuse `AgentLoopRuntime`'s existing `AgentStepLimitReached` and atomic whole-batch admission.
   Preserve the Feature 135 advisory envelope and add only the candidate scope/identity needed to
   tell a provider request which budget is active. Do not add a second counter or clock.
4. Add a bounded candidate-generation diagnostic projection at the adapter/generator boundary.
   Prefer exact typed exceptions/events and fixed local categories over parsing exception strings.
   Carry only counts, enum values, bounded timings, and identity digests. Preserve existing
   `EvolutionError` text compatibility for callers that depend on it while exposing the richer
   diagnostic to the observer/report path.
5. Mark completion only after `_draft` or `parse_bundle_agent_draft` succeeds. Ensure all failure
   paths leave incomplete work unpublished and map runtime/tool/parser boundaries without
   reclassification. Do not write a candidate record on a rejected batch or incomplete result.
6. Add focused offline fixtures first, then update shared runtime/evolution tests and documentation.
   Inspect Feature 134 files with a byte/hash inventory after implementation.

## Proposed contract names

The implementation may choose repository-local names, but the externally reviewed shape should be
recognizable as:

- `CandidateGenerationBudget`: immutable effective `max_tool_steps`, wall timeout reference, and
  authority/budget identity; it is created by the controller/generator, never by the model.
- `CandidateGenerationDiagnostic`: bounded schema projection with `schema_version`, `outcome`,
  `stage`, identity, step counters (`tool_steps_used` and `tool_steps_remaining`), attempted
  calls, and optional elapsed/timeout observations.
- Existing `AgentStepLimitReached` / `AgentStepLimitEvidence`: retained as the typed runtime
  boundary for whole-batch admission failures.

Names can remain internal if the observer and tests assert the fixed fields and outcome vocabulary.

## Alternatives rejected

- Raising the global `max_steps` or silently adding a second runtime allowance would invalidate the
  registered authority and make historical failures impossible to interpret.
- Retrying the same model turn, repairing a response, or executing a fitting prefix would create
  unregistered work and partial candidate side effects.
- Treating scratch files as a candidate would bypass the final tool-free response and parser
  authority already required by native evolution.
- Parsing arbitrary `EvolutionError` prose or provider text would leak unbounded/private data and
  conflate runtime, parser, and execution boundaries.
- A new token/cost ledger for this feature would imply accounting that the unprofiled runtime does
  not possess; token and cost remain null unless an existing profile supplies them.

## Verification strategy

Use deterministic local model turns and temporary workspaces. Assert request copies, advisory
identity, transcript bytes, tool-call counters, observer payloads, candidate publication, and the
absence of side effects after each failure. Run focused candidate/runtime tests, shared evolution
regression, Ruff, compileall, Specify prerequisite checks, `git diff --check`, and the full
two-stage regression before any commit or push. Do not call a provider or execute retained
generated source.
