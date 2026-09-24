# Implementation plan

1. Define bounded lifecycle, attestation-consumption, process-registration, stream-capture, and
   execution-receipt DTOs with canonical self-digests and fixed failure codes.
2. Implement an atomic no-follow attestation nonce claim and an exact-match consume-once guard;
   persist the claim before attempting `Popen` and make replay fail closed.
3. Add a gate-aware no-shell launcher using `Popen(shell=False, start_new_session=True,
   close_fds=True)`, then verify executable identity and exact PID/PGID ownership before writing
   and fsyncing the registration receipt. On Darwin, copy the final verified bytes into a private
   immutable snapshot and bind that snapshot digest to registration and terminal receipts; keep
   pathname execution explicitly prototype-only on platforms without a descriptor-bound path.
4. Release the gate only after registration is durable. Drain stdout/stderr concurrently under
   fixed byte ceilings and record only bounded counts, truncation flags, and digests.
5. Enforce one monotonic wall-clock deadline across waits, capture, owner-checked cleanup, and
   output observation. Use `process_ownership.cleanup_registered_process` and preserve every
   uncertain result as terminal recovery-required evidence.
6. Add no-follow, bounded, double-stat output-envelope inspection and bind its bytes, identity,
   and digest to the execution receipt. Do not parse or adjudicate producer scores here.
7. Add recovery inspection for controller interruption and unknown cleanup. It may clean the
   exact registered group but never relaunches or consumes another attestation.
8. Add provider-free fixture tests and static checks, then run the focused lifecycle suite and
   the existing offline regression. Keep automatic solve and scheduler entry points unchanged
   until a separate integration feature is specified.
