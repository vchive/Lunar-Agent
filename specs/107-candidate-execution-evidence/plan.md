# Plan

1. Add independent recorded wrapper and read-only inspector. Freeze strict bounded canonical
   intent/result/completion schemas, return DTOs and fixed error codes with the implementation.
2. Reconstruct plan/admission and caller pins before mutation. Validate source/input/attempt parent
   directory chains and disjoint identities. Require a missing caller-selected attempt path.
3. Exclusively create and sync the attempt and retain its identity. Publish and sync no-clobber
   canonical intent with declaration/file-table digests, root inodes and nonce before runner entry.
4. Invoke Feature 106 once. An exception after intent preserves uncertain evidence; it cannot be
   transformed into a fabricated returned execution or authorize another invocation.
5. Persist the validated redacted return and then completion descriptor. Sync and reread exact
   bytes/inodes before reporting completed recording; process outcome remains independent.
6. Inspect retained evidence and intended declarations read-only. Valid intent plus missing
   result/completion or any temp is uncertain. Malformed/unsafe/inconsistent evidence fails closed.
   Do not inspect post-run source/input bytes, repair, rerun or infer unknown process identity.
7. Add offline process/interruption/concurrency/filesystem tests and public exports. Update
   documentation and handoff after implementation and verification.

## Reuse boundaries

Reuse Feature 103/104 declaration replay, Feature 106 invocation and existing bounded no-follow
descriptor/directory/fsync primitives. A fixed attempt name requires exclusive creation; a helper
must not silently allocate another directory when it collides.

Do not import materialization launch/execution/attestation, controller or Store. They own a separate
single-file parent/child/task lifecycle with SQL ledger rows and recovery/attestation semantics.

Post-run validation binds returned metadata to the launch declaration. A new source/input byte
check must not be described as proving which bytes ran; the candidate may have modified them.

## Deferred work

Store ownership, exact evaluator, Candidate/receipt/archive integration, resume or repair, operator
attestation, unknown-process supervision and framework measurements require separate contracts.
Uncertain attempts remain preserved for diagnosis.
