# Tasks

- [x] T158-01 Define canonical trusted-bootstrap descriptor, protocol version, launch record, and bounded handshake/evidence DTOs.
- [x] T158-02 Define exact-byte/bootstrap allowlisting and platform execution modes without papering over Feature 156 T156-11. The current allowlist is fixture-only; platform-bound production execution remains deferred.
- [x] T158-03 Specify and implement the ready/block/release/target-start state machine in a trusted bootstrap runtime fixture.
- [ ] T158-04 Bind bootstrap and target identities to Feature 156 registration, cleanup, recovery, and one monotonic attempt.
- [x] T158-05 Add controlled fixtures proving target-marker absence before release, receipt-fsync ordering, post-release start, duplicate-token and early-EOF rejection, and group retention.
- [x] T158-06 Add a hostile direct-producer negative fixture; do not accept cooperative gate behavior as proof for arbitrary executables.
- [x] T158-07 Defer Feature 154/156/157 integration, scheduler/default entry points, publication, and external campaign validation to a later feature.

The runtime fixture now propagates one absolute monotonic deadline through normal and exceptional
cleanup and bounds the final leader reap. This is supporting evidence for T158-04; it does not
bind the fixture to Feature 156 registration, recovery, or a production scheduler entry point.
The child now defers target path validation until after gate release; a fixture with an absent
target still emits `bootstrap_ready` and only reports `target_start_failed` after release.
Post-release target identity failures, including a hard-linked target, also emit the fixed
`target_start_failed` frame rather than falling through to an unclassified early EOF.

T158-04 remains open at the lifecycle-integration level.  The provider-free
`TrustedBootstrapRegistration` DTO now covers the narrow identity boundary: it carries the
launch/journal/run/parent/task, intent, attestation, bootstrap descriptor, target identity, and
gate protocol from `TrustedBootstrapLaunch`, adds the registered bootstrap PID/PGID, and binds
`registration_sha256` to the strict canonical payload.  Parsing can require an exact launch
match, but the DTO does not read registration files, inspect processes, invoke a provider, or
wire the fixture into Feature 156 cleanup/recovery.
The fixture runtime now constructs and parses this DTO before durable registration publication,
and the release-order test verifies the persisted payload binds back to the exact launch. This is
fixture-level evidence only; Feature 156's production runner and recovery path remain separate.
