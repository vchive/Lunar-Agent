# Feature 150: explicit producer bundle bridge

**Status**: Provider-free implementation slice

## Problem

The generic `lunar-producer-result-v1` envelope intentionally describes a flat list of
material files. Repository-oriented producers can emit several files for one candidate, but
the flat envelope does not say which files belong together or which file is the entrypoint.
Inferring a bundle from directory names, ordering, lineage, or producer scores would make an
external producer an implicit authority and could combine unrelated source files.

## Outcome

Add a read-only bridge that accepts an explicit list of `BundleGroup` records. Each group names a
unique bundle ID, one entrypoint, and a non-empty set of paths already declared as
`candidate_source` materials in a completed producer envelope. The bridge projects the group to
the existing `CandidateSourceBundle`, verifies every declared byte against the producer metadata,
and returns a verified bundle result with producer provenance only.

## Contract

The bridge requires the caller's algorithm contract digest and producer fingerprint to match the
envelope. An optional producer ID is checked when supplied. Bundle IDs, entrypoints, and paths
are bounded, normalized, credential-free relative paths. IDs are unique, paths cannot repeat in a
group or be reused across groups, and the entrypoint must be a member of its group. Every grouped
path must be present in the envelope and have kind `candidate_source`; ungrouped materials are
ignored and never guessed into a bundle.

The bridge reuses the existing `CandidateSourceBundle` and source verifier. It therefore keeps
regular-file, UTF-8, size, SHA-256, inode/device and read-race checks, and returns the canonical
bundle digest and file table. It does not copy, stage, execute, evaluate, score, admit a seed,
launch a producer, write a campaign root, or treat external evidence as an authoritative score.

The existing single-file producer handoff and `lunar-producer-result-v1` bytes remain unchanged.
This feature is an explicit preparation API; wiring a producer launcher or automatic population
entrypoint is a separate feature.

## Acceptance

1. A valid two-file group returns one canonical `CandidateSourceBundle` with a stable digest and
   verified file table.
2. Multiple groups can be prepared independently, with no path or bundle-ID overlap.
3. Missing, undeclared, duplicated, reused, non-candidate, or changed materials fail with fixed
   path-free errors before a result is returned.
4. Contract, producer fingerprint, optional producer ID, status, and envelope shape are bound.
5. Symlinked/unsafe roots and source files, inode replacement, byte changes, non-UTF-8 bytes,
   and size/digest mismatches remain rejected by the existing verifier.
6. Preparation performs no filesystem writes and does not call an evaluator or producer.
7. Existing single-file producer tests and public imports remain compatible.
8. Focused tests, Ruff, compileall, diff checks, and the existing regression suites pass.

## Non-goals

- No OpenEvolve or Shinka launcher, scheduler, network client, or producer execution.
- No automatic grouping from lineage, directories, filenames, scores, or timestamps.
- No migration of old envelopes and no change to seed admission or population selection.
- No model, provider, campaign, WebAgent, or new effectiveness measurement.
