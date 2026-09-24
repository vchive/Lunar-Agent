# Implementation plan

1. Define canonical trusted-bootstrap descriptor, launch record, handshake frame, and bounded
   bootstrap evidence DTOs with fixed codes and self-digests.
2. Specify the trusted implementation allowlist and platform execution mode. Reuse Feature 156's
   exact-byte requirement; do not claim that a pathname recheck closes T156-11.
3. Define the startup state machine: ready, gate-blocked, released, target-started, and terminal
   failure. The bootstrap must perform no target work before release.
4. Bind Feature 156 registration and receipt chaining to the bootstrap PID/PGID, target pin,
   launch/intent/attestation digests, and one monotonic execution attempt. No second attestation
   or budget widening is allowed.
5. Add controlled provider-free fixtures: trusted bootstrap with pre-gate marker, target with
   post-release marker, hostile direct producer, duplicate token, early EOF, target group escape,
   and registration fsync failure. Assert no successful trusted-bootstrap receipt for invalid
   ordering.
6. Keep Feature 154 preflight, Feature 156 lifecycle, Feature 157 request evidence, output
   publication, automatic solve, and scheduler entry points unchanged until a later integration
   feature implements this contract.

## Implemented fixture slice

The provider-free runtime in `src/lunar_evolution/trusted_bootstrap_runtime.py` now exercises the
descriptor allowlist, ready/block/release/target-start handshake, durable registration ordering,
target identity recheck, process-group retention, bounded cleanup, fixed deadline, duplicate/early
gate rejection, and hostile direct-producer rejection. It intentionally remains `fixture-only` and
is not exported through the package scheduler path. The remaining integration task must supply
platform-bound exact-byte execution and Feature 156 registration/recovery ownership before any
external producer can use this boundary. The one-time target PGID observation cannot prove that a
target or its descendants never leave the registered group after start; production admission must
resolve that escape boundary before claiming complete cleanup or trusted pre-gate containment.
