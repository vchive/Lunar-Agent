# Feature Specification: Provider-free acceptance evidence observer

**Created**: 2026-09-22  
**Status**: Implemented as an offline observer slice; real provider execution remains outside scope.

## Problem

The real automatic multi-file acceptance plan defines a manifest and an ordered evidence chain,
but a read-only tool was missing to check those boundaries before any launch or after an attempt.
Without one strict observer, a preparation result or a later artifact could be mistaken for a
complete primary result.

## Scope

The observer validates an observation-manifest identity, the six planned stage receipts
(preparation, generation, execution, scoring, selection, delivery), and the fixed budget values
from the acceptance plan. It reuses the native candidate-generation receipt parser when generation
events are supplied. It returns a bounded projection with first missing/failed stage. Preparation,
primary and joint remain `0/1`: structural closure cannot replace
the independent artifact and lifecycle audit needed to establish success.

The observer is read-only and provider-free. It does not launch requests, execute candidate code,
run an evaluator or holdout, resume a run, mutate Store state, or claim joint success. The joint
counter remains `0/1`; this API never makes a real acceptance decision.

The companion campaign inventory API reads a retained directory using descriptor-relative file
access, binds every regular file by size and SHA-256, and rechecks entry identities before returning.
It rejects symlinks, non-regular entries, oversized files and directory-entry races. A later audit
recomputes the inventory and compares it read-only. This verifies retained bytes, not stage semantics
or a successful campaign; it never opens SQLite or executes retained material.
The directory must be quiescent: two bounded scans detect observed changes, without claiming an
atomic snapshot. Limits are 4,096 files, 8,192 total entries including directories, depth 64,
32 MiB per file and 256 MiB total. The inventory record must be kept outside the scanned tree.

## Safety contract

Manifest and receipt objects are strict canonical JSON. Identities and SHA-256 digests are bound to
the manifest; receipts must be an ordered prefix and later stages cannot repair an absent or failed
stage. Private-shaped manifest keys are rejected and arbitrary diagnostics are never copied into
the result. The fixed budgets are the values registered by the real-acceptance plan; changing one
requires a new plan/observer contract.

Native generation evidence must be a reusable sequence, is inspected once and reused for source
and budget binding, and must match the exact `completed`/`failed`/`unknown` outcome. Malformed
containers and cyclic manifest values raise a bounded observation error. This draft does not check
identity freshness against history, pushed Git state, campaign root existence or registered input
bytes. The full launch registration remains separate work.
