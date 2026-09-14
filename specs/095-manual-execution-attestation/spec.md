# Feature 095: Explicit execution evidence attestation

**Created**: 2026-09-14
**Status**: In progress

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
  running a candidate. Reject missing/temp-only, drift, malformed, duplicate or reused nonce.
- FR-095-03: Refuse attestation when any 088 output or 089 terminal downstream evidence exists;
  unknown or concurrent state preserves all evidence. Record one durable attestation event in the
  same FULL transaction; no exactly-once or external operator authentication is claimed.
- FR-095-04: CLI dispatch occurs after explicit receipt parsing but before any candidate execution;
  successful use may initialize normal storage only after all receipt and source checks pass.
  Fixed errors never expose secrets or raw commands. Test offline interruption, replay, drift,
  downstream evidence and source preservation.

## Limits

Attestation is local operator authorization and audit evidence, not cryptographic identity or proof
that the process actually ran. It cannot rebuild missing execution bytes or terminal/output records,
identify surviving processes, or guarantee delivery.
