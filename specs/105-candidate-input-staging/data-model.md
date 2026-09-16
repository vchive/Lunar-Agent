# Data model

`StagedCandidateExecutionInputs` is a frozen result containing the detached, revalidated Feature
104 `CandidateExecutionAdmission` and local `input_path`. Metadata and digests are derived from
the admission; the path is excluded from `to_dict()` and every canonical identity.

`CandidateInputStagingError` carries only a fixed `candidate_input_staging_*` code. Existing
`CandidateExecutionError` remains the structural/pin failure type.

There is no durable staging schema, score, validity flag, receipt, process ID, or recovery token.
The caller owns successful directories and their cleanup; repeated calls allocate fresh children.
