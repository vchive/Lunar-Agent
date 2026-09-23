# Implementation plan

1. Define bounded immutable launch-intent, executable-identity, authority, budget, attestation,
   and preflight DTOs with strict canonical JSON parsing and self-digests.
2. Require a caller-supplied `CandidateIntegrityAuthority` and explicit expected run,
   parent-task, and task IDs. Compare the complete authority projection and identity tuple without
   loading or inventing a Feature 152 plan or Feature 153 journal.
3. Add provider-free zero-write preflight. It must verify the executable bytes and no-follow
   identity, safe system-derived paths, argument vector, envelope path, and independent budgets.
4. Return `preflight_passed` as a read-only observation. Do not call it admission or execution
   permission, and do not create a lock, receipt, marker, Store row, plan, or journal.
5. Preserve the one-time attestation contract for the later process-registration feature. Exact
   run/parent-task/task, intent, executable bytes, and inode identity are required there; preflight
   neither consumes nor persists the attestation.
6. Document the post-output bridge: verify producer-result-v1 and explicit groups, construct
   Features 150–153 artifacts, then compare their authority and reserved journal ID with the
   launch intent before publication.
7. Export only the provider-free DTO/preflight API, add focused canonical/tamper/no-write tests,
   and run Ruff, compileall, diff checks, and the normal regression suite.
8. Defer actual process launch, scheduler execution, durable receipts, cleanup recovery, and real
   external campaign validation to a later feature.
