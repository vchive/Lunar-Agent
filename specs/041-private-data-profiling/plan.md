# Implementation Plan: Private Data Profiling

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Technical context

Conversational input staging already persists path/size/SHA-256 and Feature 037 copies the same
descriptors into candidate workspaces. Feature 041 profiles the intake run's `data/raw/*` bytes
immediately before evaluator-bundle compilation, writes one canonical profile into the bundle, and
adds its digest to the aggregate evaluator fingerprint.

## Decisions

1. **Structure only** — no raw values, samples, extrema, categorical labels, or free-text snippets.
2. **Exact ledger binding** — read only paths described by `CandidateInputArtifact`, verify bytes
   first, and align them with contract `InputSpec` by `data/raw/<path>`.
3. **Conservative typing** — a column with incompatible observed scalar kinds is `mixed`; empty
   observations are `null`. Numeric strings remain strings.
4. **Strict parsers** — duplicate headers, malformed records, non-object structured rows, excessive
   nesting/width/count, or unsupported formats fail before model invocation.
5. **Profile in bundle identity** — `input-profile.json` becomes the fifth exact frozen file and its
   digest participates in `bundle_sha256`.
6. **Recompute on resume** — the loader receives an expected profile digest derived from current
   staged bytes; changed data cannot reuse historical evaluator semantics.

## Data flow

```text
staged input ledger -> digest verify -> strict local parser
                                      -> private structural profile
                                                   |
contract ------------------------------------------+-> evaluator compiler
                                                       -> probes/freeze
                                                       -> profile-bound fingerprint
```

## Recovery and safety

- Parser work is bounded by existing 16 MiB file limits plus row/field/nesting limits.
- Symlink components and destination escapes fail before reads.
- Profile serialization is canonical and scanned to ensure no accidental sample fields exist.
- Profile artifacts remain in the intake bundle and are never copied to Agent generation workspaces.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Uses Python stdlib readers only. |
| Local-First and Durable State | Pass | Profile is local, canonical, hashed, and resumable. |
| Runtime Adapter Isolation | Pass | Runtime receives data-only structural context. |
| Artifact-First Verification | Pass | Exact staged bytes are checked before profiling. |
| Bounded Autonomy | Pass | No samples/values, strict formats, parser limits. |
| Test-First Recovery | Pass | Privacy, format, drift, and integration tests precede code. |

## Complexity tracking

No CLI flag, database migration, dependency, service, or strategy API change. The profile is active
only under Feature 040's explicit `--compile-evaluator` path.
