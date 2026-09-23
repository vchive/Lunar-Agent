# Implementation plan

1. Define bounded immutable launch-intent, executable-identity, budget, attestation, and
   admission DTOs with strict canonical JSON parsing and self-digests.
2. Add a read-only authority snapshot that derives the producer-batch root from the Feature 153
   journal and verifies the supplied executable, argument vector, output paths, grouping digest,
   and Feature 152/153 digests without opening a write transaction.
3. Add provider-free zero-write admission. It must reject every drift or unsafe path before
   invoking any subprocess, evaluator, provider, scheduler, Store mutation, or filesystem write.
4. Define the future process receipt and cleanup interface around the existing process-ownership
   primitives, including exact PID/PGID registration, owner locks, one monotonic wall deadline,
   and fail-closed unknown recovery. Keep this interface declarative in the first slice.
5. Define the output-envelope bridge that hands a completed, exact-budget producer result and
   explicit groups to Features 150–153 without accepting producer scores as authority.
6. Export only the provider-free DTO/admission API, add focused tamper and no-write fixtures, and
   run Ruff, compileall, diff checks, and the normal regression suite.
7. Defer actual process launch, scheduler execution, durable launch receipts, cleanup recovery,
   and real external campaign validation to a follow-up feature that consumes this contract.
