# Feature 106: Bounded candidate execution runner

## Status

Implemented. This feature defines the offline runner boundary consumed by Features 103–105. It
starts one already admitted multi-file candidate and reports bounded process outcome. It does not
score, register, publish, or resume a candidate.

## Problem and scope

Feature 103 materializes a private source workspace, Feature 104 binds the immutable execution
declaration, and Feature 105 stages declared inputs in a separate private tree. A runner is
needed to join those identities at one launch boundary without copying inputs into source or
allowing ambient process state to decide what ran.

The runner accepts a validated `CandidateWorkspacePlan`, a matching
`CandidateExecutionAdmission`, the materialized workspace, and the staged input directory. It
rechecks all declarations and physical trees immediately before `execve`, launches exactly one
process group with an argv vector (never a shell), and enforces finite time/output limits with the
currently supported single-process admission. It returns a path-free execution result and has no
evaluator or Lunar score authority.

## Acceptance scenarios

1. A valid plan, admission, source workspace, and staged input tree launch once with the declared
   absolute executable and argv followed by the bundle's relative entrypoint. The child working directory is the private workspace and the
   reserved input namespace is exposed as `LUNAR_CANDIDATE_INPUT_ROOT`; declared logical targets
   resolve below that directory only.
2. Before process creation, the runner revalidates plan/admission pins, source bundle file table,
   staged input count/bytes/digests, directory identity (device/inode), and no-symlink ancestry.
   Any mismatch fails before `Popen` and before candidate import or dependency resolution.
3. The command is passed as an argv sequence with `shell=False`, `stdin=DEVNULL`, an explicit
   environment, fixed cwd, and a fresh process group. No shell expansion, PATH lookup,
   inherited descriptors, network setup, package installation, or provider call is performed.
4. Timeout, output, process-start, non-zero-exit, signal, and cleanup failures map to fixed
   `candidate_execution_runner_*` codes. The runner kills the complete process group and waits for reaping;
   uncertain cleanup is reported as failure and never treated as success.
5. A successful run returns only status, exit code/signal, duration, bounded stdout/stderr
   metadata, and identity digests. It never writes Candidate, score, rank, receipt, archive,
   recovery token, or Store state. Any execution evidence is caller-owned and explicitly marked
   non-authoritative.
6. Re-running the same declaration is a new attempt with a new attempt identifier. The runner
   does not deduplicate, resume, or infer exact-once semantics from an old result.

## Frozen contract

Protocol `lunar-candidate-execution-runner-v1`, schema `1`.

The input namespace is the staged input root supplied by the caller. The runner requires a
physical directory with no symlink ancestors and injects one reserved environment entry:
`LUNAR_CANDIDATE_INPUT_ROOT=<absolute runtime path>`. The key cannot occur in the plan
environment. The path is launch-local and is never included in canonical digests or returned
JSON. A candidate must treat the root as read-only; writes, traversal outside the root, and
undeclared names are outside this contract. Source workspace and input root must be disjoint.

The effective command is the plan command followed by the bundle's validated relative entrypoint,
with no shell or other implicit arguments. The executable must remain the same absolute file checked by the plan caller;
the runner checks it is a regular executable and records only its caller-supplied fingerprint.
The environment is the sorted plan environment plus the reserved input-root key. `PATH`, HOME,
proxy, locale, and other ambient values are absent unless explicitly declared.

Physical limits are the admission budget: timeout seconds, maximum output bytes, maximum input
bytes, and `max_processes == 1`. Limits are checked before launch; the process group is terminated
on timeout or overflow and the direct child is reaped within a finite cleanup grace period. The
runner does not monitor a candidate's own fork count.

## Errors and evidence boundary

Public errors use only these fixed codes: `candidate_execution_runner_invalid`,
`candidate_execution_runner_workspace_unsafe`, `candidate_execution_runner_input_unsafe`,
`candidate_execution_runner_plan_mismatch`, `candidate_execution_runner_bundle_changed`,
`candidate_execution_runner_input_changed`, `candidate_execution_runner_executable_unsafe`,
`candidate_execution_runner_process_start_failed`, `candidate_execution_runner_process_timed_out`,
`candidate_execution_runner_output_limit_exceeded`, `candidate_execution_runner_process_failed`,
and `candidate_execution_runner_process_cleanup_failed`.
Messages contain no local paths, command arguments, input bytes, environment values, OS exception
text, PIDs, or secrets.

The Python result may retain bounded UTF-8 stdout/stderr for the immediate caller; its serialized
form contains only byte counts and fixed error/status fields, plus plan/admission/bundle digests,
input counts and the relative entrypoint. It must not contain absolute paths, source bodies, staged
bytes, evaluator output, scores, ranks, process identifiers, or host environment values. A result is
execution telemetry only; a later exact evaluator and receipt feature must independently authenticate
and bind any score.

## Non-goals

No evaluator invocation, output-contract validation, Candidate/archive/ledger mutation, durable
execution receipt, recovery/resume, external framework adapter, model/provider call, dependency
installation, sandbox guarantee, or claim of algorithmic/WebAgent performance is included.
