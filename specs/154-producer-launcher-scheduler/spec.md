# Feature 154: declarative producer launch intent and preflight

**Created**: 2026-09-24

**Status**: provider-free, zero-write preflight implemented; real launcher remains deferred

## Problem

Features 150–153 verify producer output, construct a native admission plan, and publish that plan
through a recoverable transaction. They deliberately do not define the declaration that exists
before an external producer runs: which executable is expected, which run and task own it, where
its output will live, and which request and wall-clock limits apply.

The admission plan and publication journal are generated from producer output. Requiring their
content digests in a prelaunch intent would create a circular dependency: the producer cannot
write its output until the intent is accepted, while the plan and journal cannot exist until that
output has been verified. A prelaunch check must therefore bind only immutable launch facts and
leave plan/journal content binding to the post-output path.

## Outcome

Define a canonical `ProducerLaunchIntent`, its embedded authority projection, and a read-only `ProducerLaunchPreflight` result. The
intent fixes the reserved launch and journal identities, run/task ownership, complete
`CandidateIntegrityAuthority` projection, producer identity, executable and argument pins,
system-derived work/output paths, and independent request/output/wall-clock budgets.

`preflight_producer_launch` compares the intent with an explicitly supplied integrity authority
and expected run/parent-task/task tuple, rechecks the executable and safe derived paths, and
returns `preflight_passed` or a fixed rejection code. It does not authorize execution, write a
receipt, create a journal, or start a process.

An explicit one-time attestation remains part of the future process-registration boundary. It is
not required to perform preflight and is not a user approval gate for this feature.

## Scope

This feature covers:

* bounded canonical launch intent and preflight DTOs;
* exact comparison with a caller-supplied `CandidateIntegrityAuthority` and expected IDs;
* no-follow, read-only validation of the configured executable and workspace roots;
* independent producer request, output-byte, and total wall-clock budget binding; and
* the future attestation, process-ownership, cleanup, and post-output hand-off boundaries.

The implementation is provider-free. It may hash and inspect local files, but it does not call a
model, network service, evaluator, producer, scheduler loop, or subprocess API. A preflight result
cannot be used as evidence that a producer ran.

## Launch intent contract

`ProducerLaunchIntent` is immutable and canonical. Its digest is computed over canonical JSON with
`intent_sha256` omitted. No unknown fields are accepted. It contains:

* `schema_version="1"` and `protocol="lunar-producer-launch-intent-v1"`;
* bounded `launch_id` and reserved `journal_id` values. The journal ID is an intended identity
  for the eventual producer batch; preflight does not require a journal file or journal digest;
* bounded `run_id`, `parent_task_id`, and `task_id` values;
* the complete bounded authority projection supplied by `CandidateIntegrityAuthority`: schema
  version, contract,
  evaluator kind and fingerprint, dependency, environment, runner, and generator identities;
* `producer_id` and `producer_fingerprint`, used as provenance and later output pins;
* an executable descriptor containing a configured producer-root label, normalized relative
  executable path, SHA-256, byte size, device/inode, and `mtime_ns`/`ctime_ns` values;
* a bounded argument vector and its canonical `argv_sha256`. Arguments are ordinary UTF-8
  values, cannot contain credentials or shell control text, and never imply a shell invocation;
* normalized working and output directories below the system-derived producer-batch root;
* the fixed envelope path `producer-result.json`; and
* `request_timeout_seconds`, `max_requests`, `output_max_bytes`, `wall_timeout_seconds`, and
  `intent_sha256`.

The intent has no `admission_sha256`, `journal_sha256`, grouping digest, candidate identity, or
publication state. Those values do not exist until producer output has been verified. The
post-output hand-off must compare the eventual Feature 152 plan and Feature 153 journal to the
authority and IDs from this intent before any publication transaction.

The executable descriptor is checked during preflight and again immediately before any future
spawn. A changed byte, size, device, inode, or timestamp is authority drift. The producer root
must be a regular, no-follow directory. A path string never establishes identity by itself.

The intent contains no credential, prompt, response, provider body, arbitrary exception, or
unbounded environment value. Environment selection is represented by the authority digest only;
future launch code must obtain secrets through its process-local mechanism and must not put them
in argv, the intent, or public status.

## Authority-bound, zero-write preflight

The operation is conceptually:

```text
preflight_producer_launch(
    workspace,
    intent,
    producer_root=...,
    candidate_integrity_authority=authority,
    expected_run_id=..., expected_parent_task_id=..., expected_task_id=...,
) -> ProducerLaunchPreflight
```

The caller must supply the authority object and all three expected IDs. Preflight does not infer
them from a path, an intent, a database row, an old journal, or a producer result. It compares:

1. every authority field in the intent with the supplied `CandidateIntegrityAuthority`;
2. `intent.run_id`, `intent.parent_task_id`, and `intent.task_id` with the expected values;
3. the executable bytes and no-follow file identity with the pinned descriptor; and
4. working/output paths, envelope path, argument vector, and all budget bounds.

The output directory is derived as
`workspace/evolution/producer-batches/<journal_id>/<output_directory>`. Existing ancestors are
checked for regular directory/no-symlink identity; missing directories are acceptable and are
never created. The reserved journal ID is validated as a bounded identifier, but no journal
content, plan digest, archive prefix, or publication state is required or read.

`ProducerLaunchPreflight` has status `preflight_passed` or `rejected`, the intent and budget
digests, executable identity, derived output directory, and
`registration_attestation_required=true`. `preflight_passed` is a read-only observation that the
declarations are internally consistent. It is not execution permission, process ownership, a
scheduler admission, or a publication authority. The field says which later registration
boundary still applies; it does not request user approval.

All failures use fixed, path-free codes. No directory, lock, marker, intent file, Store row,
temporary file, archive, state, source tree, receipt, or process is created or modified. No
producer, evaluator, provider, or subprocess is invoked.

## One-time attestation for a future registration

The future process-registration operation requires an explicit one-time
`ProducerLaunchAttestation`. Preflight does not consume or persist it. The attestation contains:

* the exact launch, reserved journal, run, parent-task, and task identifiers;
* the exact `intent_sha256`;
* the executable SHA-256, byte size, device, inode, `mtime_ns`, and `ctime_ns`; and
* a bounded non-reusable nonce and attestation digest.

Only when the run/parent-task/task tuple, launch-intent bytes, executable bytes, and executable
inode identity all match may a later registrar record process ownership. A mismatch, reused nonce,
missing field, or uncertain read fails closed without starting or retrying a producer. This rule
is a future launch-registration condition, not a requirement for the current read-only
preflight.

## Budget contract

The intent carries three independent ceilings:

* `request_timeout_seconds` bounds one producer request;
* `max_requests` bounds the number of requests the producer declares for this launch; and
* `wall_timeout_seconds` bounds one future active producer execution from its launch gate through
  verified process termination and output-envelope observation.

`output_max_bytes` is an independent material/output ceiling. All values are finite, positive,
and included in the canonical intent digest; the wall value must be at least the request timeout.
A continuation cannot widen or replace them.

The future launcher can enforce process wall time and output size locally, but preflight cannot
claim enforcement of provider token or cost limits. Post-output evidence must include bounded
observed request counters and reject missing, over-limit, or contradictory budget evidence. A
timeout or unobserved process is `unknown` and requires explicit recovery; it never receives a
fresh budget through automatic relaunch.

## Future process ownership and cleanup contract

The later launcher must use the existing local process-ownership primitives and record the exact
intent digest before opening a work gate. It must start without a shell in a new process group,
register the exact PID/PGID, hold the owner lock until output verification is complete, re-check
ownership before each signal, and retain incomplete-cleanup evidence.

Missing PID evidence is not proof of exit, and creating a second scheduler instance is not proof
that the first owner died. Timeout, liveness uncertainty, output-write uncertainty, or cleanup
uncertainty is terminal `unknown`/`recovery_required`; the producer must not be silently replayed.
These operations are specified for a later feature and are not implemented by this preflight
slice.

## Post-output hand-off to Features 150–153

After a producer has written output, a later feature verifies the existing
`lunar-producer-result-v1` envelope and explicit multi-file grouping. It then performs the fixed
sequence:

```text
producer-result-v1 + explicit groups
  -> Feature 150 verified bundles
  -> Feature 151 native drafts
  -> Feature 152 admission plan
  -> Feature 153 publication journal and transaction
```

At that point the caller must compare the plan and journal's run/task identity and complete
authority projection with the launch intent. The reserved `journal_id` becomes the actual journal
identity; the plan/journal content digests are first introduced there. A mismatch fails closed
before any publication stage. Feature 154 itself does not parse producer output or mutate a
Feature 153 journal.

## Non-goals

This feature does not launch a producer, implement a scheduler loop, create a background worker,
create a plan or publication journal, persist a launch or attestation receipt, evaluate output,
enforce remote token/cost limits, publish an archive, retry an unknown process, or perform a real
external campaign. It makes no quality, parity, or effectiveness claim.

## Acceptance criteria

1. Canonical intent, attestation, budgets, and preflight DTOs round-trip with stable digests and
   reject duplicate, unknown, oversized, credential-bearing, or non-canonical fields.
2. Preflight requires a caller-supplied `CandidateIntegrityAuthority` and expected run,
   parent-task, and task IDs; authority or identity drift rejects before any side effect.
3. Executable bytes, size, device/inode/timestamps, argv, derived paths, envelope path, and budget
   drift reject before any side effect. Preflight does not require or read plan/journal content.
4. Only an explicit one-time attestation whose run/parent-task/task tuple, intent digest, and
   executable byte/inode identity match can authorize a future process registration. Attestation
   is not needed for the current preflight and is not persisted by it.
5. `preflight_passed` is a read-only consistency observation, never runtime or publication
   authorization.
6. Preflight success and every rejection leave Store, journal, archive, state, source trees,
   locks, markers, temporary files, and process tables unchanged.
7. Post-output hand-off requirements preserve the Features 150–153 sequence and never promote
   producer scores to local authority.
8. Focused provider-free tests, Ruff, compileall, diff checks, and the existing full regression
   suite pass. No external producer or campaign is started.
