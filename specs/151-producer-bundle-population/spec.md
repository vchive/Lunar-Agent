# Feature 151: producer bundle to native population draft

**Status**: Provider-free projection slice

## Problem

Feature 150 verifies explicit producer groups but deliberately stops before the native multi-file
population code. The existing `CandidateDraft(source_files=...)` and
`MultiFileCandidatePipeline` already provide the local execution and evaluation boundary. A small
adapter is needed to move verified bytes into that shape without inventing a second source
protocol or trusting producer scores.

## Outcome

`prepare_producer_bundle_drafts` re-verifies each `VerifiedProducerBundle`, decodes its declared
UTF-8 files, and returns immutable `ProducerBundleDraft` values. Each value contains a native
multi-file `CandidateDraft` and producer provenance metadata. The function is read-only and does
not evaluate, stage, launch, or write a campaign.

## Contract

Bundle IDs and source paths are unique within one call. Every file is rechecked against the
canonical bundle digest, including regular-file, size, SHA-256, inode/device, and read-race
checks. The entrypoint is retained as `draft.filename`; all files are retained in
`draft.source_files`. Producer evidence is provenance only and cannot become a score or candidate
identity. The resulting draft is suitable for the existing native multi-file population pipeline.

## Non-goals

- No producer launcher, scheduler, network transport, or real campaign.
- No change to the single-file `SeedManifest` or producer envelope bytes.
- No automatic population admission, archive publication, evaluator invocation, or delivery in
  this projection slice; those operations remain explicit caller actions through the native
  pipeline.
