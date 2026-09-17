# Feature 121: Explicit evaluator generation protocol

## Problem and outcome

Feature120 accepted both contracts, then both evaluator requests timed out at 600 seconds before
response headers arrived. Offline reconstruction matches the registered request hashes: the
requests have one isolated system message and one user message, no tools/history, and one copy
of the contract/profile. No response exists to identify a parser failure or the server's cause.

Independent code review does identify an incomplete generation protocol. Compiler/auditor prompts
omit nested probe/file/ordering shapes and report detail/error shapes, advertise the standard
library more broadly than the actual source validator permits, and do not explain that negative
business probes must still pass output schema checks. Auditor wording also confuses constructing
synthetic values with recovering private values. Fix these independently established defects.

## Acceptance

1. Both prompts supply the complete exact response shape: version, coverage IDs, probe name,
   constraint_id, integer expected_validity, file path/content, and better/worse ordering names.
   Compiler additionally supplies objective/source types; auditor receives no compiler self probes.
2. Examples explain structure only and are explicitly placeholders, never assumed task answers.
   All inputs and required outputs are included in each probe, paths remain declared, negative
   probes remain schema-valid, and each output constraint gets exactly one invalid probe with a
   matching error code. Valid probes use constraint_id=null and two distinct valid names in ordering.
3. Explain source validation with the actual import allowlist and prohibited calls/attributes,
   read-only pathlib usage, normal entry point, no external files, and no candidate execution.
   Snapshot and legacy candidate layouts remain distinct; the snapshot report identity remains fixed.
4. Give exact nested report types and finite/nonnegative score rules, error requirements, and
   existing byte/count limits using implementation constants. Recommend small synthetic instances
   and only the required coverage, without dropping constraints or claiming the source file count.
5. Generate synthetic values from declared semantics; never recover/infer private values from the
   structural profile. Preserve complete contract/profile context and its hashes.
6. Preserve parsers, source validator, report rules, coverage/preflight, model settings, number of
   runtime calls, isolated transport, frozen bundle identity and terminal resume. No repair/fallback,
   retry, new model request or historical campaign mutation. Confirm with offline process tests.

## Limits

This improves protocol specificity, not a demonstrated timeout or completion-rate fix. Existing
probe-capacity limits remain: at most 64 probes (including two valid),32 files per probe,512KiB
aggregate content. Output constraints that require malformed/missing schema-level output cannot
necessarily be expressed as schema-valid negative business probes. No free-text heuristic silently
removes those requirements. No universal compilability guarantee or execution-behavior validation.
