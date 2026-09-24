# Tasks

- [ ] T156-01 Define canonical lifecycle, attestation-consumption, registration, stream, envelope, and execution-receipt DTOs with bounded fixed failure codes.
- [ ] T156-02 Implement no-follow atomic consume-once nonce claims and exact revalidation of intent, authority IDs, attestation, and executable identity.
- [x] T156-03 Implement the gate-aware no-shell `Popen` path with a new session, closed descriptors, derived cwd, and exact PID/PGID owner registration for cooperating local producers.
- [x] T156-04 Persist a launch registration receipt with bounded fsync/atomic publication before releasing the producer work gate.
- [ ] T156-05 Add one monotonic wall-clock deadline, independent request/output limits, concurrent bounded stdout/stderr capture, and deterministic overflow handling.
- [ ] T156-06 Integrate owner-checked process-group cleanup and fail-closed timeout, liveness, signal, and cleanup uncertainty states.
- [x] T156-07 Add no-follow, bounded, double-identity output-envelope evidence and bind stable bytes to the execution receipt.
- [x] T156-08 Add read-only controller-interruption recovery that inspects exact registrations and never relaunches or consumes another attestation.
- [ ] T156-09 Add provider-free fixture tests for success, replay, gate, timeout, capture, tampering, cleanup, receipt durability, and recovery.
- [ ] T156-10 Run focused tests, Ruff, compileall, diff checks, and the existing offline regression; keep integration entry points unchanged.
- [ ] T156-11 Close the executable replacement window with a platform-supported byte-bound execution contract and a deterministic replacement regression before external admission.
