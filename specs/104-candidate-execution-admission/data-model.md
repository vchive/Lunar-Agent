# Data model

`CandidateExecutionInput` is an immutable descriptor with `target`, `source_label`, `size`, and
`sha256`. It contains no local source path or bytes. Targets are sorted by Unicode codepoint and
must be unique under the conservative case-folded path rule.

`CandidateEvaluatorPin` is an immutable `{kind, fingerprint}` pair. `CandidateExecutionBudget` is
an immutable bounded tuple of timeout, output bytes, input bytes, and process count.

`CandidateExecutionAdmission` is a frozen, path-free DTO containing the validated Feature 103 plan
digest, bundle/contract identities, sorted input descriptors, dependency/environment identities,
evaluator pin, optional output-contract identity, and budget. Its canonical digest excludes any
local workspace path and excludes the self-referential `admission_sha256` field.

`VerifiedCandidateExecutionAdmission` contains the admission DTO, its digest, and observed input
metadata only. It does not contain input bodies, evaluator output, process IDs, or recovery rights.

`CandidateExecutionError` exposes only fixed `candidate_execution_*` codes. Structural parsing and
validation are separate from optional byte verification so a caller can replay the same DTO without
filesystem IO.
