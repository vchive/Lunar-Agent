# Research: Evolution Result Handoff

## Existing seam

`CandidateArchive.result()` already computes the same validity-first `best()` value used by every
native strategy. Each `Candidate` stores a workspace-relative `code_path`, and persistence rejects
unsafe paths. `StrategyResult.to_dict()` is serialized unchanged by the controller into
`evolution/result.json` and the `evolution_finished` event; CLI status reuses that event payload.

## Decision

Add one optional field to `StrategyResult` and populate it in `CandidateArchive.result()` from the
selected candidate's existing `code_path`. Validate the path against the archive workspace and
require a regular file before exposing it. This avoids duplicating archive parsing in callers and
does not add a database migration or external dependency.

## Alternatives considered

1. **Expose the full candidate record** — rejected because it duplicates archive data and expands
   the parent-Agent response unnecessarily.
2. **Expose an absolute filesystem path** — rejected because it is machine-specific and violates
   portable run-relative handoff boundaries.
3. **Have the controller search `archive.jsonl`** — rejected because the strategy already owns the
   canonical selection operation; duplicating it risks disagreement with validity-first ranking.
