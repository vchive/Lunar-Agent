# Plan

Add a small terminal-publication module, with the controller supplying its existing replay
validator as a callback. The module retains canonical result bytes, an identity journal and a
completion receipt in `evolution/materialization/.terminal-publication/`. A sibling process lock
serializes terminal publishers only; execution locking is outside this feature.

The write order is stage fsync → journal fsync → SQLite prepared receipt → no-clobber final marker
and directory fsync → SQLite atomic terminal batch → filesystem completion receipt. Preparation
and commit use exact deterministic event identities; the terminal batch preserves the old parent
event payload while adding a journal acknowledgement. Recovery distinguishes absent, prepared,
committed, partial and unknown evidence before mutating anything. A present completion receipt
requires the marker and complete terminal batch, never repair.

The controller invokes recovery after Feature 088 reconciliation and before its existing marker
and execution gates. New results use the new publisher; legacy complete results still use strict
`_record_materialization_result(... require_existing_*=True)` checks. Candidate execution evidence
is a prerequisite and is never created or repaired by terminal publication.

## Alternatives and complexity

Blindly adding missing terminal rows would turn deletion of previously committed evidence into
silent repair. SQLite-only batching cannot reconcile a crash after the marker appears. A durable
preparation receipt and a separate completion receipt distinguish normal incomplete work from
damaged completed work using the existing event schema, without a new service or dependency.
The per-result journal and two small acknowledgement events are justified by this recovery gap.

## Verification

Use deterministic controller and Store fixtures with injected file/SQLite failures and bounded
real subprocess exits. Validate cached tamper rejection, no runner calls during recovery, exact
legacy compatibility, and the complete repository regression. Do not modify historical sealed
Feature 051/074/076/078/082 files or historic 084–088 test results.
