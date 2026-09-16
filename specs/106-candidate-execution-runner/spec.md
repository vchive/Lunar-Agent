# Feature 106: Bounded candidate execution runner

## Status

Implemented. This feature defines the offline runner boundary for the outputs of Features 103–105. It
starts one already admitted multi-file candidate and reports bounded process outcome. It does not
score, register, publish, or resume a candidate.

## Problem and scope

Feature 103 materializes a private source workspace, Feature 104 binds the immutable execution
declaration, and Feature 105 stages declared inputs in a separate private tree. A runner is
needed to join those identities at one launch boundary without copying inputs into source or
inheriting an implicit command or environment.

The runner accepts a validated `CandidateWorkspacePlan`, a matching
`CandidateExecutionAdmission`, the materialized workspace, and the staged input directory. It
rechecks declarations and declared files before process creation, starts one process group with
an argv vector (without an implicit shell), and enforces finite time/output limits with the
currently supported single-process admission. It returns path-free serialized metadata and has no
evaluator or Lunar score authority.

## Acceptance scenarios

1. A valid plan, admission, source workspace, and staged input tree launch once with the declared
   absolute executable and argv followed by the bundle's relative entrypoint. The child working
   directory is the private workspace and the reserved input namespace is exposed as
   `LUNAR_CANDIDATE_INPUT_ROOT`; declared logical targets are relative to that directory.
2. Before process creation, the runner revalidates plan/admission pins, source bundle file table,
   staged input count/bytes/digests, directory identity (device/inode), and no-symlink ancestry.
   It also opens and rechecks the declared executable's directory chain and file metadata. A
   mismatch detected by these checks fails before `Popen`, candidate import or dependency resolution.
3. The command is passed as an argv sequence with `shell=False`, `stdin=DEVNULL`, an explicit
   environment, fixed cwd, and a fresh process group. The runner adds no shell expansion, PATH
   lookup, inherited descriptors, network setup, package installation, or provider call. A shell
   explicitly chosen as the plan executable still interprets the candidate entrypoint.
4. Timeout, output, process-start, non-zero-exit, signal, and cleanup failures map to fixed
   process outcome codes in `result.execution.error`. The runner kills the process group and waits
   for reaping; uncertain cleanup is reported as failure and never treated as success.
5. A run's serialized form contains status, exit code (negative for a signal), duration,
   bounded stdout/stderr metadata, and identity digests. Python callers may also inspect the bounded
   stdout/stderr text. The runner never writes Candidate, score, rank, receipt, archive, recovery
   token, or Store state. Any execution evidence is caller-owned and non-authoritative.
6. Each invocation is independent. The runner does not expose an attempt identifier, deduplicate,
   resume, or infer exact-once semantics from an old result.

## Frozen contract

The runner has no separately serialized request schema. It consumes the existing
`lunar-candidate-workspace-plan-v1` plan and `lunar-candidate-execution-admission-v1` admission.

The input namespace is the staged input root supplied by the caller. The runner requires a
physical directory with no symlink ancestors and injects one reserved environment entry:
`LUNAR_CANDIDATE_INPUT_ROOT=<absolute runtime path>`. The key cannot occur in the plan
environment. The path is launch-local and is never included in canonical digests or returned
JSON. A candidate must treat the root as read-only; writes, traversal outside the root, and
undeclared names are outside this contract. This runner does not provide filesystem or network
sandboxing. Source workspace and input root must be disjoint.

The effective command is the plan command followed by the bundle's validated relative entrypoint,
with no implicit shell or other arguments. The plan command has at most 32 items; the final argv
has at most 33 items after adding the entrypoint. The runner opens the executable's full directory
chain and regular file without following symlinks, holds those descriptors, and rechecks
device/inode, size, mode, mtime and ctime before `Popen`. The plan and returned metadata contain no
executable fingerprint or filesystem identity. These checks observe preflight state; the child is
started with the declared path, so they do not atomically bind the executable at `exec` time or
authenticate its dependencies.
The environment is the sorted plan environment plus the reserved input-root key. `PATH`, HOME,
proxy, locale, and other ambient values are absent unless explicitly declared.

The plan timeout and output ceiling must fit the admission budget, and declared input bytes must
fit its input ceiling. `CandidateExecutionRunner(max_output_bytes=...)` may override the plan's
output ceiling within the admission limit. The current runner accepts only `max_processes == 1`
and does not monitor a candidate's own fork count. Execution uses the plan timeout; termination and
reaping use a separate finite cleanup grace period after that deadline. The output ceiling applies
to each pipe separately, while retained text is capped at 16 KiB per stream. Timeout or output
overflow terminates the process group.

## Errors and evidence boundary

`CandidateExecutionRunnerError` uses only these fixed codes: `candidate_execution_runner_invalid`,
`candidate_execution_runner_workspace_unsafe`, `candidate_execution_runner_input_unsafe`,
`candidate_execution_runner_plan_mismatch`, `candidate_execution_runner_bundle_changed`,
`candidate_execution_runner_bundle_mismatch`, `candidate_execution_runner_contract_mismatch`,
`candidate_execution_runner_identity_mismatch`, `candidate_execution_runner_budget_invalid`,
`candidate_execution_runner_input_changed`, `candidate_execution_runner_executable_unsafe`,
`candidate_execution_runner_process_start_failed`, `candidate_execution_runner_process_timed_out`,
`candidate_execution_runner_output_limit_exceeded`, `candidate_execution_runner_process_failed`,
and `candidate_execution_runner_process_cleanup_failed`.
Exception messages contain no local paths, command arguments, input bytes, environment values, OS
exception text, PIDs, or secrets. Process outcomes are returned instead of raised: their `error`
field is `process_start_failed`, `process_timed_out`, `output_limit_exceeded`, `process_failed`, or
`process_cleanup_failed`, without the exception prefix; successful runs use `None`.

The Python result may retain bounded UTF-8 stdout/stderr for the immediate caller; child output can
include local paths or other candidate-supplied text. `CandidateExecutionRun.to_dict()` omits that
text and contains only byte counts and fixed error/status fields, plus plan/admission/bundle
digests, input counts and the relative entrypoint. Its serialized form excludes absolute paths,
source bodies, staged bytes, evaluator output, scores, ranks, process identifiers, and host
environment values. Output byte counts describe retained text, not the total bytes emitted by the
child. A result is execution telemetry only; a later exact evaluator and receipt feature must
independently authenticate and bind any score.

## Non-goals

No evaluator invocation, output-contract validation, Candidate/archive/ledger mutation, durable
execution receipt, recovery/resume, external framework adapter, model/provider call, dependency
installation, sandbox guarantee, or claim of algorithmic/WebAgent performance is included.
