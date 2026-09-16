# Data model

`CandidateExecutionRun` is immutable metadata around the existing `CandidateExecution` value. It
contains status, bounded duration and output byte counts, plan/admission/bundle digests, input
count/bytes and the validated relative entrypoint. Local workspace and staged-input paths are
request-only values and never participate in serialized identity.

`CandidateExecutionRunner` performs the launch boundary with explicit argv, fixed cwd, reserved
input-root environment and bounded pipe reads. It accepts only `max_processes == 1`; it does not
claim to enforce process counts inside the candidate.

Python callers may inspect bounded stdout/stderr on `CandidateExecutionRun.execution`; `to_dict()`
deliberately omits those text fields. The value contains no paths, process IDs, source/input bytes,
environment values, scores, or evaluator reports.

`CandidateExecutionRunnerError` exposes only a fixed `candidate_execution_runner_*` code. It is safe to serialize and
does not preserve underlying OS exception text.
