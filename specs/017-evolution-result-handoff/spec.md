# Feature Specification: Evolution Result Handoff

**Feature Branch**: `017-evolution-result-handoff`
**Created**: 2026-09-03
**Status**: Implemented
**Input**: Expose the verified best algorithm candidate to standalone and parent-Agent callers

## Context and scope

The local evolution strategies already persist every candidate under the run workspace and return
the best candidate ID. A parent Agent still has to infer the source path from the archive schema,
which couples callers to an internal layout and makes JSON handoff unnecessarily fragile. This
feature adds one additive, run-relative `best_candidate_path` to strategy results and the existing
CLI/status/event artifacts. The path is derived only from the canonical archive record after
validity-first selection; no Agent claim or unverified path can become a handoff.

## User Stories & Testing

### User Story 1 - Consume the verified best candidate (Priority: P1)

As a parent Agent or local script, I want the evolution result to include the best candidate source
path so that I can read or copy the selected artifact without knowing archive internals.

**Independent Test**: Run loop and population with a valid fixture evaluator and assert that the
returned path is run-relative, points to the selected candidate, and remains below the workspace.

### User Story 2 - Preserve fail-closed handoff (Priority: P1)

As a problem owner, I want failed or all-invalid runs to return no best path, so callers cannot
mistake a rejected candidate for a deliverable.

**Independent Test**: Run a strategy whose evaluator rejects every candidate and assert both
`best_candidate_id` and `best_candidate_path` are null.

### User Story 3 - Keep existing integrations compatible (Priority: P2)

As an existing CLI or library caller, I want the new field to be additive across result JSON,
`evolution_finished`, `result.json`, and `status --json` without changing existing fields.

**Independent Test**: Existing evolution, delegation, resume, and status tests remain green while a
CLI fixture sees the new field in all result views.

## Functional Requirements

- **FR-1701**: `StrategyResult` MUST expose an optional `best_candidate_path` field containing a
  normalized path relative to the evolution run workspace, or null when no valid best exists.
- **FR-1702**: The path MUST be derived from the selected valid archive record and MUST point to a
  regular file confined below the run workspace before it is returned.
- **FR-1703**: Loop, population, and OpenEvolve results MUST use the same result field without
  changing their selection, archive, or evaluator behavior.
- **FR-1704**: CLI evolve output, `evolution_finished` event payload, `evolution/result.json`, and
  `status --json` MUST expose the additive field through their existing result payloads.
- **FR-1705**: Runs with no valid candidate MUST return null for both best candidate ID and path;
  rejected candidates MUST never be handed off as best artifacts.
- **FR-1706**: The field MUST remain bounded, portable, and free of absolute paths or credentials.

## Success Criteria

- **SC-1701**: A parent process can consume one JSON response and open the verified best source using
  `workspace / best_candidate_path`, without parsing `archive.jsonl`.
- **SC-1702**: All-invalid and evaluator-failure runs expose no best path.
- **SC-1703**: Full existing test, lint, compile, and Spec Kit checks remain green.

## Out of scope

- Copying the best candidate outside the run workspace.
- Automatically executing, delivering, or modifying the selected source.
- Changing candidate ranking, evaluator semantics, or the archive format.
