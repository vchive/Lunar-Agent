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

## Implemented formal observation slice

The formal-attempt observer reads the Feature 156 batch claim, its nonce ledger counterpart,
formal registration, and optional bootstrap evidence while holding no-follow directory chains.
It compares the claim bytes exactly and delegates canonical, digest, and cross-record identity
checks to `verify_trusted_bootstrap_attempt`. Missing or unknown terminal evidence requires
recovery; missing or inconsistent prerequisite records fail closed. The observer never inspects
process liveness or grants cleanup authority. The production runner still needs platform-bound
bootstrap execution, durable publication of these records, and explicit recovery semantics.

Fixture recovery also compares the target-start PGID retained in evidence with its durable
fixture registration before reporting either terminal or unknown evidence. This is read-only and
does not establish continued group membership.

## Production execution prerequisites

The fixture's `python -m` child hashes a source file but executes an interpreter with imported
dependencies, so it cannot serve as the production exact-byte bootstrap. A production entry needs
a Lunar-owned executable artifact with an installation-controlled allowlist covering its execution
closure. Feature 156 must bind that artifact to the actual spawned bytes through its platform
mechanism, then separately bind the attested target bytes passed to the bootstrap for post-gate
execution. The Darwin bootstrap and target need distinct immutable snapshots; Linux needs sealed
descriptors held through the relevant exec operations. If either binding cannot be established,
the consumed attempt remains unresolved and the gate is never released. Only after both bindings
exist should the formal runner publish its shared registration, release the gate, and reuse the
same process owner, lock, cleanup, receipt, and recovery path.

Darwin snapshot preparation now reserves separate immutable paths within one batch:
`.producer-snapshots/bootstrap` and `.producer-snapshots/target`. The ordinary Feature 156
producer retains `.producer-snapshots/executable`. The formal trusted-bootstrap registration
validator requires the bootstrap path for Darwin. These role-specific names support the pair
preparer below; the current fixture still executes via `python -m` and reopens its target by
pathname. The native bootstrap artifact, target handoff, and shared Feature 156 lifecycle
integration remain prerequisites for T158-04.

The proposed formal registration now includes separate target binding mode, snapshot path,
SHA-256, and size alongside the bootstrap execution fields. The formal validator checks platform
mode, role-specific path, and target digest; cross-record observation checks target size against
the attestation. These fields are a strict proposed registration contract, not proof that a
sealed target FD was inherited or that an immutable target snapshot was actually executed.

The unexported `prepare_trusted_executable_pair` context now takes one verified launch,
descriptor, attestation, private batch, and absolute deadline. It binds bootstrap and target
separately: Darwin yields two immutable snapshot paths; Linux yields two sealed memfd paths and
the FDs that must be inherited by the future bootstrap process. Darwin rejects an already occupied
role path. A failed second binding cannot yield a pair; returned snapshots are checked after
pre-spawn cleanup, and uncertain cleanup is reported explicitly. After a successful Darwin
preparation, the caller must retain the snapshots until terminal process quiescence; leaving the
context does not silently remove possible recovery evidence. The helper neither verifies the
installation allowlist nor consumes the attestation, spawns, persists registration, passes a
target FD into a child, releases the gate, or performs recovery. T158-04 remains open.
Publication can fail before a snapshot object is returned; a remaining role path is then
reported as cleanup-unknown and retained because its inode is not owned by the preparer.
The formal runner must hold exclusive batch ownership across preparation and publication.
