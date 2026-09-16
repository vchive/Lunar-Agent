# Data model

`CandidateExecutionRun` is immutable metadata around the existing `CandidateExecution` value. Its
`to_dict()` contains status, bounded duration and output byte counts, plan/admission/bundle digests,
input count/bytes and the validated relative entrypoint. Workspace and staged-input paths are
request-only values and are not serialized.

`CandidateExecutionRunner` performs the launch boundary with explicit argv, fixed cwd, reserved
input-root environment and bounded pipe reads. It accepts only `max_processes == 1`; it does not
claim to enforce process counts inside the candidate.

There is no runner request DTO, attempt identifier, or separately serialized protocol. Callers
provide the existing workspace plan and execution admission. The executable's directory chain and
file metadata are held and rechecked before launch, but neither the plan nor result contains an
executable fingerprint, and starting the declared path does not atomically bind executable identity.

Python callers may inspect bounded stdout/stderr on `CandidateExecutionRun.execution`; `to_dict()`
deliberately omits those text fields. Only this serialized metadata is path-free; child output may
contain local paths or other candidate-supplied text. Byte counts describe the retained, bounded
UTF-8 text rather than the total emitted bytes.

`CandidateExecutionRunnerError` exposes only a fixed `candidate_execution_runner_*` code and does
not preserve underlying OS exception text. Process outcomes use the unprefixed fixed codes in
`CandidateExecutionRun.execution.error`; success uses `None`.
