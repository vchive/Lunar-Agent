# Research: Verified Retry Feedback

## Decision 1: Build feedback from durable events, not raw task errors

**Decision**: `_build_task_prompt` reads the latest task-scoped failed evaluation event and derives a
small controlled summary. If no evaluation exists, it uses a generic runtime-failure marker.

**Rationale**: Evaluator details already distinguish acceptance rules and evidence. Raw
`task.last_error` and attempt errors may contain paths, credentials, or provider text; copying them
into a model prompt amplifies sensitive data and creates a second audit source.

**Alternative rejected**: Append `task.last_error` verbatim; it is useful for debugging but violates
the bounded, non-secret feedback boundary.

## Decision 2: Feedback is prompt context, not a new mutable task definition

**Decision**: Keep the SQLite task prompt immutable. Add an attempt-scoped feedback section only to
the prompt string written for the new attempt.

**Rationale**: Plan/task revisions remain the authority for user intent. Retry feedback is evidence
from execution, not an instruction that should alter future revisions or affect other runs.

## Decision 3: Normalize evaluator details conservatively

**Decision**: Traverse only known acceptance rule names (`result_contains`, `artifact_exists`,
`artifact_text_contains`, `json_parse`, `json_has_keys`, `all`, `any`) and include at most 16 short
rule/evidence codes. Ignore unknown or malformed data.

**Rationale**: Persisted events can outlive code versions. A fail-closed bounded projection remains
safe when details are legacy, manually edited, or unexpectedly shaped.

## Decision 4: No new schema or event is required

**Decision**: Existing prompt artifacts provide the audit record. The existing `task_evaluated`
event remains the source evidence; no migration is added.

**Rationale**: Feedback is a deterministic view, not an independent state transition. Avoiding a
schema change preserves SQLite compatibility and idempotent retry behavior.
