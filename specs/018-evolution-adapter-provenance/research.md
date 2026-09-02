# Research: Evolution Adapter Provenance

## Existing seam

`EvolutionConfig.to_dict()` already stores a SHA-256 digest for `command`, which protects the
explicit OpenEvolve command and the Feature 015 Agent solver command. Native command generator and
evaluator options are currently injected into callables but are not represented in state. CLI
resume compares the serialized config before creating/claiming work, and the strategy repeats the
same check when loading state.

## Decision

Add optional `generator_fingerprint` and `evaluator_fingerprint` fields to `EvolutionConfig`. The
CLI computes each from a canonical JSON object containing the command vector and adapter profile;
only the digest is persisted. `to_dict()` omits unset fields so callback-only and legacy state
payloads remain compatible. New command-backed runs include the fields, and both CLI and strategy
state checks reject drift before execution.

## Alternatives considered

1. **Persist raw command strings** — rejected because arguments can contain credentials or local
   paths and are unnecessary for equality checks.
2. **Hash executable bytes** — rejected because it is expensive, follows mutable dependencies, and
   still does not capture role/capability semantics.
3. **Trust the caller on resume** — rejected because detached runs would silently combine evidence
   produced by different solver/evaluator behavior.
