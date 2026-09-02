# Research: Artifact Acceptance Contracts

## Decision 1: Use a declarative interpreter, not a model judge or command hook

The first verifier accepts a small JSON-like rule tree and evaluates it in-process. It never starts
a subprocess, calls a Runtime Adapter, imports a provider SDK, or accesses the network. This gives
repeatable evidence and prevents an acceptance field from becoming a hidden tool-execution API.

**Alternatives considered**:

- Model-as-judge: useful for semantic quality later, but non-deterministic, provider-dependent,
  costly, and not independently verifiable.
- Shell assertions: expressive but violate the local safety boundary and complicate recovery.
- JSON Schema: mature but adds a dependency and a much larger surface than the top-level key check
  needed for the first local contract.

## Decision 2: Scope artifact paths to one attempt workspace

The controller already creates `tasks/<task>/<attempt>/` as the Runtime Adapter workspace and
writes the result/audit files beneath the same run workspace. The acceptance evaluator resolves
every declared relative path against that attempt workspace and requires the resolved candidate to
remain below it. This also catches an existing symlink that points outside the workspace.

**Alternative considered**: Checking the run workspace would allow a task to accidentally accept
a stale result from another attempt or task. Scheduler dependencies already provide the safe way to
consume predecessor outputs.

## Decision 3: Preserve existing acceptance syntax by compiling it

A plain string and `{ "contains": "..." }` become the canonical
`{ "result_contains": "..." }` rule. Task database rows remain text, so the interpreter accepts
either a Python object or JSON-serialized object. Existing external plans and immutable revision
comparisons retain their behavior.

## Decision 4: Keep structured and human-readable evidence together

`Evaluation.evidence` stays a tuple of concise strings for existing callers. An additive
`Evaluation.details` mapping carries the rule tree and observations. Controller events,
`evaluation.json`, and status summaries serialize both. No migration is needed because events are
already JSON payloads.

## Decision 5: Bound all parsing and file reads

Contracts have bounded byte size, depth, and number of rules. Rule text/path/key values are bounded
and credential-scanned. Artifact text and JSON parsing read at most a fixed number of bytes; a
larger file fails that rule rather than being partially accepted. This preserves a deterministic
evidence size and avoids consuming arbitrary local files.
