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
