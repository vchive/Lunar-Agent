# Feature 124: Explicit snapshot evaluator request schema

## Problem and outcome

Feature 123's sole compiler response passed static envelope/source/probe parsing, but preparation
failed before audit or freeze. A sufficient static defect is its input descriptor lookup using
`path`; native requests serialize `target/source_label/size/sha256`. The snapshot prompt described
the file layout but omitted the input descriptor shape. It also said `output/<path>` although an
output descriptor's path already includes `output/`. Correct the shared compiler/auditor prompt.

## Acceptance

1. Advertise the exact request top-level keys, nested input/output/evaluator/binding fields and
   types. Include one clearly illustrative JSON shape; its empty contract object stands for the
   canonical contract supplied once in the task context. Paths, labels, digests and limits are
   examples, never task values or an executable request. No private values or host paths enter it.
2. Runtime input descriptors use `target`, never `path`. Read `inputs/<target>`, preserving nested
   directories. Contract input `path` equals target; profile/probe input `path` uses `data/raw/`.
   The private structural profile is generation context, not a runtime request field.
3. Output descriptor `path` is read verbatim, already prefixed by `output/`. Describe present and
   absent descriptors, byte sizes and digests. Optional missing outputs are allowed; required or
   schema-invalid outputs fail before harness invocation. Zero-byte inputs are valid descriptors;
   this does not relax nonempty contract input declarations or nonempty synthetic probe content.
4. Treat source_label as an opaque label, and binding/evaluator metadata as identities/settings,
   not filenames or objective values. Keep read-only snapshot execution and strict report rules.
5. Validate advertised shapes against native parsers and actual local synthetic preflight and
   production evaluation requests. A fresh independent synthetic fixture must succeed using target
   and fail using path; do not reuse or execute the private 123 generated source.
6. Preserve parsers, source validation, request construction, process/model settings and call counts,
   frozen identity, candidate invocation and terminal resume. No retry/repair, migration, model
   request, campaign slot reuse, or historical evidence change.
7. Preserve reproducible regression after the product changes. The original full run exposed 24
   historical registration tests whose fixture requires the frozen 519fea5 product. Execute current
   tests and those exact historical nodes in two explicit stages, with the latter in an isolated
   5560eb9 checkout whose product matches the registration. Verify imports and pinned bytes, fail
   overall on either stage, clean up the temporary checkout, and use the same entry point in CI.
   Do not alter historical tests, relax product_changed, or silently skip/xfail the tests.

## Limits

This is a protocol clarification with offline evidence. It does not establish a real-model success
rate or latency improvement. Historical 113/115/117/120 remain separately 0/2 and 123 remains 0/1.
A follow-up measurement requires a separate fixed registration committed and pushed before calls.
