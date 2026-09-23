# Feature 152: explicit producer bundle admission descriptor

**Status**: Provider-free admission binding slice

## Problem

Feature 151 projects verified producer material into native multi-file drafts, but a future
archive transaction still needs a durable descriptor that binds those drafts to the local contract
and execution authority. Passing the drafts through a generic generator would lose the producer
batch identity on resume and could silently admit a different bundle set.

## Outcome

`build_producer_bundle_admission_plan` validates a bounded batch of `ProducerBundleDraft` values,
recomputes each native bundle digest, checks provenance metadata, and binds the batch to contract,
evaluator, runner, dependency, and environment SHA-256 identities. The immutable plan has a
canonical digest suitable for a future archive admission journal and resume comparison.

## Contract

- Input order is retained for caller-controlled island assignment.
- Bundle IDs and material paths are unique within the batch.
- The draft bundle digest must equal the verified producer bundle digest.
- Producer identifiers and envelope digests are provenance only; no producer score is accepted.
- The builder is read-only and provider-free. It does not execute candidates, evaluate sources,
  write an archive, launch a producer, or alter the single-file `SeedManifest` protocol.

## Non-goals

Archive publication, per-candidate execution, resume transaction recovery, launcher/scheduler
integration, automatic solve integration, and real external-producer validation remain follow-up
work. A later transaction must use this descriptor before writing or evaluating an external batch.
