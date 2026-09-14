# Feature 096: External producer CLI warm start

**Created**: 2026-09-14
**Status**: Complete

## Problem

Shinka export and generic producer admission already exist as Python APIs. CLI users cannot export
native Shinka results or feed producer envelopes into Lunar population without writing glue code.
Expose the existing material boundary through a usable CLI workflow.

## Requirements

- FR-096-01: Add `export-shinka-result RESULTS_ROOT --output NEW_ROOT --contract FILE
  --producer-fingerprint SHA256`, with mutually exclusive ordered/repeatable `--program-id` or
  `--top-k`, and optional `--producer-run-id`. Dispatch before normal configuration initialization.
  Reuse the existing offline exporter; no model, evaluator, scheduler or Shinka process is started.
- FR-096-02: Add `evolve --producer-result ROOT --producer-fingerprint SHA256` and optional
  `--producer-id`. It is a population-only alternative to `--seed-manifest`, requiring the existing
  command-backed local exact evaluator. Reject ambiguous/orphan pins and seed identity overrides.
- FR-096-03: Factor generic producer validation and manifest construction into a shared public
  preparation API. This creates an unadmitted SeedManifest in memory after the existing bounded
  envelope/material/contract/pin checks. Only normal controller seed admission evaluates candidates
  and grants receipts; external score/correctness never become Lunar scores or iteration counts.
- FR-096-04: Reuse existing seed resume/revalidation and detached-run mechanisms. Forward producer
  options exactly, preserve stable identities, and reject changed envelope/source/evaluator pins.
  Preparing a manifest does not run a producer, admit candidates, or write source material.
- FR-096-05: Provide CLI help and an end-to-end documented command sequence. Verify export,
  warm start, local score authority, invalid candidates, resume and detached option forwarding with
  offline fixtures. Preserve existing behavior and the 601 sealed measurement files. No real
  provider/framework run, new measurement or push is part of this feature.

## Limits

The CLI accepts already completed local single-file producer material. Shinka's quiescent database
and existing source/export restrictions remain; live runner control, network sync, benchmark
comparison, repository/workflow candidates and effectiveness claims are outside this feature.
