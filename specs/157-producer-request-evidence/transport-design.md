# Controller-owned request transport boundary

`HostRequestLedger` is a provider-free accounting primitive for a future controller-owned
request broker. The controller creates it from the immutable Feature 156 launch intent.
At the broker's entry point, before any outbound I/O, the controller calls `admit` with a
bounded opaque request ID. The ledger reserves one of at most 16,384 request slots and
returns an identity-bearing admission and a controller-monotonic deadline. A controller
that actually performs the outbound I/O calls `finish` with its own terminal result, or
`expire` when its deadline fires. The producer cannot supply duration or terminal timing.

The resulting snapshot says `coverage=brokered_requests_only`. It must not be translated
into the cooperative `ProducerRequestEvidence` DTO, whose clock is explicitly the SDK
clock, or into a complete host-enforcement receipt. `within_broker_limits` refers only
to admitted requests that reached a terminal event. The ledger is owned by one controller
event loop; concurrent brokers need serialization around admission and terminal events.

`HostRequestJournal` now persists each admission and terminal event to a new, bounded
append-only file. Each canonical JSON line carries an ordinal, previous-record digest,
and self-digest. It is fsynced before the ledger state advances. The first line binds the
exact launch/journal/run/parent/task tuple, intent digest, and request budgets. A failed
write poisons that journal handle. Read-only recovery validates every line and reports
unclosed admissions as uncertain, without resuming them. It rejects symlinked file and
ancestor paths. The controller must place this file in an OS-protected directory that the
producer cannot write; a hash chain alone does not authenticate bytes against a child
that can edit the journal with the controller's credentials.

## Required production integration

1. The controller must own the actual request transport. Only its broker can call the
   provider, and the producer runtime must have no alternative provider network or
   credential path. Pin and attest that runtime alongside the launch intent. Otherwise
   the host can prove only that *brokered* requests were observed.
2. The controller must apply each admission's deadline to all transport phases and
   cancel/close the underlying I/O at the deadline. The ledger records deadlines but
   does not interrupt a blocking transport. Wall-clock polling after a call returns is
   insufficient to claim per-request enforcement.
3. Integrate the bounded append-only host journal with the actual transport owner, and
   isolate its directory from the producer. Recovery already treats a missing terminal
   event as uncertain, but cannot infer whether a remote request continued after a crash.
   No producer-written file can fill that gap.
4. Feature 156 can set `request_timeout_enforced` only after all three conditions above
   are tested against a fixture that bypasses the broker, one that hangs during I/O, and
   one that crashes the controller after admission. Until then, retain the existing
   declaration-only and process-wall-time semantics.

The current implementation completes bounded host accounting and a fixture-level durable
journal. It does not implement the broker, egress restriction, cancellation, protected
production journal ownership, or Feature 156 integration, so T157-05 and T157-06 remain open.
