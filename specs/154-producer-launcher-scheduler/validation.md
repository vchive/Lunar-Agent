# Feature 154 validation

Feature 154 is an SDD-only slice at this checkout. No launcher, scheduler, process registration,
or external producer is started by the specification work, so there is no runtime acceptance
claim yet.

The implementation acceptance matrix is:

| Area | Required evidence |
| --- | --- |
| Canonical DTOs | Intent, attestation, budget, and admission parse/serialize with stable self-digests; duplicate, unknown, oversized, credential-bearing, and non-canonical fields reject. |
| Authority binding | Plan/journal/run/task, contract, executable bytes, size, device/inode/timestamps, argv, output root, grouping, and budget drift reject before any side effect. |
| One-time attestation | Only an explicit exact-match attestation can authorize a future registration; nonce reuse, run/parent-task/task mismatch, intent mismatch, byte mismatch, and inode replacement fail closed. |
| Budget isolation | Per-request timeout/count, output bytes, and active wall-clock values are independent immutable ceilings; continuation cannot widen them. |
| Zero-write admission | Success and every rejection leave Store, journal, archive, state, source trees, locks, markers, temporary files, and process tables unchanged. No subprocess/provider/evaluator call is observed. |
| Output bridge | Completed `lunar-producer-result-v1` plus explicit grouping reaches Feature 150/151/152 inputs only after source byte/inode checks; producer scores remain provenance. |
| Future lifecycle contract | Process receipt, exact PID/PGID cleanup, owner lock, monotonic deadline, and `unknown` recovery rules are represented in provider-free fixtures without launching a process. |
| Regression | Focused tests, Ruff, compileall, diff checks, and the full existing offline suite pass; no real campaign or historical measurement is run. |

The first implementation should add a no-write snapshot around the admission call and assert that
all existing files retain their bytes and identities. Actual process-launch and scheduler tests
belong to the follow-up feature that implements `FutureProducerLaunchReceipt`.
