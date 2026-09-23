# Feature 154 validation

Feature 154 implements the provider-free, zero-write launch-intent and preflight slice. No
launcher, scheduler, process registration, or external producer is started by this feature, so
runtime acceptance is limited to canonical offline observations and does not claim producer
execution.

The implementation acceptance matrix is:

| Area | Required evidence |
| --- | --- |
| Canonical DTOs | Intent, authority projection, attestation, budgets, and preflight parse/serialize with stable self-digests; duplicate, unknown, oversized, credential-bearing, and non-canonical fields reject. |
| Authority binding | Preflight requires a caller-supplied `CandidateIntegrityAuthority` and expected run/parent-task/task IDs; complete authority or identity drift rejects before any side effect. |
| Prelaunch independence | Intent accepts only the reserved journal ID. Missing or future Feature 152/153 plan/journal content does not block preflight and is never fabricated. |
| Executable/path checks | Executable bytes, size, device/inode/timestamps, argv, derived work/output paths, envelope path, and budget drift reject before any side effect; symlinks and traversal fail closed. |
| One-time registration attestation | Only an explicit exact-match attestation can authorize a future registration; nonce reuse, tuple mismatch, intent mismatch, byte mismatch, and inode replacement fail closed. Preflight does not consume or persist it. |
| Observation semantics | Success is exactly `preflight_passed`; it is a read-only consistency observation, never execution or publication permission. |
| Zero-write preflight | Success and every rejection leave Store, journal, archive, state, source trees, locks, markers, temporary files, and process tables unchanged. No subprocess/provider/evaluator call is observed. |
| Post-output bridge | Later output verification constructs Features 150–153 artifacts and only then binds plan/journal authority and content digests to the launch intent; producer scores remain provenance. |
| Regression | Focused tests, Ruff, compileall, diff checks, and the full existing offline suite pass; no real campaign or historical measurement is run. |

The focused launcher/preflight tests cover canonical round-trips, exact attestation matching,
authority and identity drift, executable changes, symlinked roots, and zero-write behavior. The
repository `.venv` regression, Ruff, compileall, and diff checks pass. Actual process-launch,
scheduler, and durable receipt tests belong to the follow-up feature that implements the future
registration boundary.
