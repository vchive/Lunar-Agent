# Feature 126: Shared format admission for synthetic probe inputs

## Problem and outcome

Feature 125's compiler passed self-tests built from JSON scalar inputs although real input
profiling only admits objects or arrays of objects. Independent audit used objects and prevented
freeze. Reuse the real input parser for all synthetic input files before executing a probe suite.
This detects an unsupported input representation locally; it does not establish evaluator quality.

## Acceptance

1. Provide pure input-format validation backed by the same UTF-8 and record parsing used by private
   input profiling. Preserve CSV header/width rules, JSON object or object-array roots, JSONL object
   records, text behavior, duplicate-key/nonfinite rejection and existing structural limits.
2. Before any harness in a compiler or auditor suite executes, validate every declared input of
   every probe. Apply this to candidate and snapshot invocation, including expected-invalid probes
   and later probes or later input files. Failed compiler admission prevents the auditor call;
   failed auditor admission prevents its harnesses and freeze. Existing staging cleanup remains.
3. Keep probe envelope limits and required paths. Allow small synthetic instances, different row
   counts, mixed/null values, empty object arrays and whitespace-only JSONL. Do not derive a schema
   from InputSpec.fields prose, profile field statistics or private values. Object-versus-object-array
   semantics and required business keys remain evaluator responsibilities.
4. Explain the executable input rules in the shared compiler/auditor prompt, separately from output
   schema requirements. Even an expected-invalid output requires a format-admissible input.
5. Existing frozen bundles still load and resume by their original identities without re-running
   probes or applying the new creation-time admission. No protocol/schema migration, repair,
   retry, historical evidence edit, captured source execution or real model request.
6. Validate with fresh offline fixtures: reproduce scalar self-test rejection, demonstrate valid
   preparation and independent-audit rejection, retain terminal recovery and the 112 quickstart.

## Limits and follow-up

Admission proves only membership in the supported input-format domain. It cannot guarantee
business fields, their types/ranges, consistency with the task, or general correctness. Granular
controller-owned preparation failure diagnostics are a separate next feature. Any new real
measurement needs an independent fixed registration committed and pushed before requests;
113/115/117/120 remain separately 0/2 and 123/125 separately 0/1.
