# Tasks

- [x] T157-01 Define bounded request event/evidence DTOs, canonical self-digest, and fixed parser errors.
- [x] T157-02 Bind evidence to the exact Feature 156 launch tuple, intent digest, and repeated budgets.
- [x] T157-03 Add conservative declaration-only assessment that never claims host enforcement.
- [x] T157-04 Add provider-free round-trip, duplicate/tamper, binding, partial coverage, and timeout fixtures.
- [ ] T157-05 Specify and implement a controller-owned evidence transport or controlled producer SDK.
- [ ] T157-06 Integrate Feature 156 only after transport evidence is host-observed and recovery-safe.

T157-05 progress: `transport-design.md` specifies the controller-owned broker boundary;
`HostRequestLedger` implements bounded host-side admission, count, and monotonic timing
for requests that pass through that boundary. `HostRequestJournal` records identity-bound,
append-only, fsynced events and read-only crash recovery. The actual outbound broker,
deadline-driven I/O cancellation, complete egress coverage, and protected production
journal ownership are still required.
