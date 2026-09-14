# Feature 095: Explicit execution evidence attestation

**Created**: 2026-09-14
**Status**: Complete

## Problem and scope

After a 090 launch intent, a process may leave `execution.json` before 091 preparation completes.
Automatic recovery is forbidden because raw evidence does not prove the runner outcome. Provide an
explicit local operator attestation that authorizes one exact execution registration.

## Requirements

- FR-095-01: Accept only a bounded canonical attestation file explicitly supplied by the operator;
  no automatic upgrade from raw or temporary evidence. Bind parent/child/task, launch intent digest,
  candidate/attempt identity, execution SHA-256/size/device/inode and a fresh nonce.
- FR-095-02: Under the existing lifecycle lock, revalidate no-follow regular execution bytes,
  exact launch intent and owner, then invoke the existing 091 preparation/commit path without
  running a candidate. Reject missing/temp-only, drift, malformed or conflicting/reused nonce;
  exact receipt retries are idempotent.
- FR-095-03: Refuse attestation when any 088 output or 089 terminal downstream evidence exists;
  unknown or concurrent state preserves all evidence. Record the attestation event and 091 prepared
  event together in one FULL transaction, with
  reciprocal receipt/journal digests; no exactly-once or external operator authentication is claimed.
- FR-095-04: CLI dispatch occurs after explicit receipt parsing but before any candidate execution;
  successful use may initialize normal storage only after all receipt and source checks pass.
  Freeze the parsed receipt across preflight and registration. Fixed errors never expose secrets
  or raw commands. Test offline interruption, replay, drift, downstream evidence and source preservation.

## Recovery boundaries

A complete 095 journal with no SQLite preparation can be retried only by explicitly resubmitting
its identical receipt, with no completion, journal temporary file or downstream evidence. Ordinary
resume cannot create preparation. After atomic preparation, normal 091 recovery validates the
retained receipt, completes registration and can enter 092 delivery without the original receipt
file. Missing/partial/unattested journals remain refused; they are not silently replaced.

The receipt is a local operator statement, not an algorithm performance result. CLI success means
execution registration only. Exact replay through 095 also refuses database-only downstream
records; normal 091 observation of complete execution remains compatible with later delivery.

## Limits

Attestation is local operator authorization and audit evidence, not cryptographic identity or proof
that the process actually ran. It cannot rebuild missing execution bytes or terminal/output records,
identify surviving processes, or guarantee delivery.
