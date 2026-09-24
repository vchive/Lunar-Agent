# Tasks

- [x] T158-01 Define canonical trusted-bootstrap descriptor, protocol version, launch record, and bounded handshake/evidence DTOs.
- [x] T158-02 Define exact-byte/bootstrap allowlisting and platform execution modes without papering over Feature 156 T156-11. The current allowlist is fixture-only; platform-bound production execution remains deferred.
- [x] T158-03 Specify and implement the ready/block/release/target-start state machine in a trusted bootstrap runtime fixture.
- [ ] T158-04 Bind bootstrap and target identities to Feature 156 registration, cleanup, recovery, and one monotonic attempt.
- [x] T158-05 Add controlled fixtures proving target-marker absence before release, receipt-fsync ordering, post-release start, duplicate-token and early-EOF rejection, and group retention.
- [x] T158-06 Add a hostile direct-producer negative fixture; do not accept cooperative gate behavior as proof for arbitrary executables.
- [x] T158-07 Defer Feature 154/156/157 integration, scheduler/default entry points, publication, and external campaign validation to a later feature.
