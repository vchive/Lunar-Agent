# Feature 092: Recoverable post-execution delivery

**Created**: 2026-09-14
**Status**: Complete

## Problem and scope

A complete Feature 091 execution registration still stops at a missing terminal marker.
Resume should finish independently verified delivery without executing the candidate again.
Persist the validation decision and output byte metadata before calling Feature 088, then
reconcile publication and hand the exact result to Feature 089.

## Requirements

- FR-092-01: With complete modern 090/091 evidence and no delivery/output/terminal evidence,
  resume may independently validate retained attempt outputs and prepare delivery. Raw execution
  files and legacy execution records do not authorize this transition. Never call the runner.
- FR-092-02: Persist one bounded canonical delivery plan outside the attempt cleanup target and
  register its exact digest in a FULL SQLite transaction bound to the complete 091 execution.
  Freeze the existing result identity, execution projection, validation and expected output
  path/format/fields/required/size/SHA-256 before publishing outputs. Artifact IDs and their
  owners remain selected and validated by 088; the plan does not claim to freeze them in advance.
- FR-092-03: Recovery requires exact filesystem and database plan evidence. Validate the launch,
  execution, original attempt validation and planned output bytes before any output/terminal
  recovery mutation. FS-only/DB-only, missing modern plan, partial bytes and drift fail closed.
- FR-092-04: An absent output batch may publish from the validated retained attempt. A committed
  088 batch reuses its exact projection without calling the output promoter. A verified rolled-back
  batch yields failed terminal status with no outputs; it is never republished. Reconcile only
  after comparing the batch metadata with the plan under the parent publication lock.
- FR-092-05: A prepared/committed 089 result remains authoritative and must match the plan and
  existing validators. Otherwise the plan plus exact 088 outcome authorizes preparing the result.
  Save a durable delivery completion receipt after 089 succeeds. Its final or temporary presence
  forbids rebuilding missing terminal records. Intact completed terminal evidence may finish
  a missing delivery completion receipt.
- FR-092-06: Delivery preparation checks absence of advanced evidence before filesystem writes.
  Complete legacy terminal results stay read-only without forced migration. Exact prepared 089
  results retain their recovery authorization after read-only validation of the output batch.
  For complete modern 091 execution without a delivery plan or exact terminal preparation,
  old downstream fragments are refused before output reconciliation can mutate them. Attempts
  without modern execution retain the older output recovery rules. Any 092
  filesystem/database evidence also prevents 091 from rebuilding a missing execution batch.
- FR-092-07: Unknown state never becomes a fabricated failure. Retain lifecycle locking,
  immutable contracts, reused output ownership, budgets, and no-clobber publication. Test real
  interruption, concurrency, success/failure/timeout, output commit and rollback, drift and
  legacy behavior, then run full/static/Specify/sealed checks and independent review.

## Limits

Incomplete execution preparation and incomplete delivery-plan preparation still require
diagnosis. Output publication retains 088's rollback policy and its pre-journal interruption
boundary; no retry of a rolled-back batch. Plan recovery does not reconstruct missing candidate,
execution or attempt output bytes. The protocol does not guarantee exactly-once execution or
successful delivery and does not identify surviving processes. Records have per-attempt bounds
and no GC. Advisory locks and hashes do not authenticate coordinated removal or rewriting of all
completion and ledger evidence by unrelated writers. No real model, provider, WebAgent, producer,
remote service or campaign is run; offline tests do not measure algorithm effectiveness.
