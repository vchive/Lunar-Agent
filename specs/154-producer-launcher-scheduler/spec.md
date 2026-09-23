# Feature 154: declarative producer launcher admission

**Created**: 2026-09-24

**Status**: SDD only; provider-free, zero-write dry-run/admission is the planned first slice

## Problem

Features 150–153 can verify an externally produced bundle, bind it to a native admission plan,
and publish that plan through a recoverable transaction. They deliberately do not define who may
start an external producer, which exact executable is allowed, how a launch belongs to a run and
task, or how an interrupted producer would be distinguished from a producer that completed but
whose output was not observed. Starting a command from a path or a free-form shell string would
make the process itself an implicit authority and could attach output to the wrong publication
journal.

The next boundary is a declarative launch contract. It must be possible to inspect one exact
launch request without starting anything, and to reject drift before a future launcher is allowed
to create a process or a publication side effect.

## Outcome

Define a canonical `ProducerLaunchIntent`, a one-time user-supplied
`ProducerLaunchAttestation`, and a read-only `ProducerLaunchAdmission` decision. The admission
binds one Feature 152 admission plan and one Feature 153 publication journal to a verified
executable identity, argument vector, output envelope location, independent request and wall
clock budgets, and the owning run/task identity. It performs no filesystem or Store writes and
does not launch a producer.

The contract also specifies the process, cleanup, and output evidence that a later launcher must
produce. Those later operations are separate work: this feature only reserves the exact shape
and fail-closed rules that make them safe to implement.

## Scope

This feature covers:

* canonical, bounded launch intent and attestation DTOs;
* no-follow, read-only validation of the configured executable and workspace roots;
* independent producer request and total wall-clock budget binding;
* zero-write dry-run/admission against an existing Feature 153 journal and Feature 152 plan;
* a future-facing process ownership and cleanup contract; and
* the exact output envelope hand-off consumed by Features 150–153.

The first implementation is provider-free. It may hash and inspect local files, but it does not
call a model, network service, evaluator, producer, scheduler loop, or subprocess API. A caller
cannot use this feature to create a background job or to claim that an external campaign ran.

## Launch intent contract

`ProducerLaunchIntent` is immutable and canonical. Its digest is computed over the canonical JSON
payload with `intent_sha256` omitted. The following fields are required; no unknown fields are
accepted:

* `schema_version="1"` and `protocol="lunar-producer-launch-intent-v1"`;
* bounded `launch_id`, `journal_id`, `run_id`, `parent_task_id`, and `task_id` values;
* `admission_sha256` equal to the supplied Feature 152 plan digest and
  `journal_sha256` equal to the supplied Feature 153 journal digest;
* the contract, evaluator, runner, dependency, and environment digests already bound by the
  admission plan and journal;
* `producer_id` and `producer_fingerprint`, used as provenance and exact output pins;
* an executable descriptor containing a configured producer-root label, a normalized relative
  executable path, its SHA-256, byte size, device/inode, and `mtime_ns`/`ctime_ns` values;
* a bounded argument vector and its canonical `argv_sha256`. Arguments are ordinary UTF-8
  values, cannot contain credentials, and never contain a shell expression. A shell, command
  string, glob, or implicit working-directory lookup is invalid;
* a normalized working directory and output directory below the system-derived batch directory;
  callers cannot choose a sibling, symlink, or path outside the run workspace;
* a fixed envelope path (`producer-result.json`) and, for multi-file output, a digest for the
  explicit grouping descriptor consumed by Feature 150;
* a `request_budget` with bounded per-request timeout and request count, a bounded output-byte
  ceiling, and a separate finite `wall_timeout_seconds`; and
* `intent_sha256`.

The executable descriptor is checked twice by a future launcher: once during admission and again
immediately before spawn. A changed byte, size, device, inode, or timestamp is authority drift.
The configured producer root itself must be a regular, no-follow directory. Path strings never
serve as identity without the descriptor comparison.

The intent contains no credential, prompt, response, provider body, arbitrary exception, or
unbounded environment value. Environment selection is represented by an allowlist digest only;
future launch code must obtain any secret values through its existing process-local secret
mechanism and must not put them in argv, the intent, or public status.

## One-time user attestation

Admission may be inspected without an attestation, but a future process registration or launch
resume requires an explicit `ProducerLaunchAttestation` supplied by the user for that one exact
intent. The attestation is not inferred from a PID, a directory, a producer result, or a scheduler
callback. It contains:

* the exact launch, journal, run, parent task, and task identifiers;
* the exact `intent_sha256`, executable SHA-256, size, device, inode, `mtime_ns`, and `ctime_ns`;
* a bounded, non-reusable nonce and the attestation digest.

The run/parent-task/task tuple, launch-intent bytes, executable bytes, and executable inode
identity must all match before a future launcher can register ownership. Any mismatch, reused nonce,
missing field, or uncertain read is rejected without starting or retrying a producer. The dry-run
slice does not persist the attestation; it returns the canonical attestation fields that a later
launcher must consume exactly once.

This is an authority check, not proof that a producer completed. Completion still requires the
process and output evidence described below.

## Budget contract

The intent carries two independent ceilings:

* `request_budget.timeout_seconds` bounds one producer request, and
  `request_budget.max_requests` bounds the number of requests the producer declares for this
  launch. Both are finite and positive.
* `wall_timeout_seconds` bounds one active producer execution from the future launch gate until
  the process reaches a verified terminal state and its output envelope is read. It is finite,
  positive, and at least the per-request timeout.

The output byte ceiling is independent of both time values. Every value is persisted in the
canonical intent and included in the budget digest. A continuation cannot widen or replace a
budget. The launcher can enforce process wall time and output size locally; it cannot claim to
have enforced an internal provider token or cost limit. A later output admission must therefore
include bounded observed request counters and reject missing, over-limit, or contradictory
producer-reported budget evidence.

The wall deadline is one monotonic deadline. It is not recreated for a request, retry, cleanup
poll, or envelope parse. An exhausted, timed-out, or unobserved process is `unknown` and requires
explicit recovery; it never receives a fresh allowance through automatic relaunch.

## Zero-write dry-run/admission

The planned read-only operation is conceptually:

```text
admit_producer_launch(workspace, plan, journal, intent)
  -> ProducerLaunchAdmission
```

It performs, in order:

1. strict canonical parsing and bounded-size checks for the plan, journal, and intent;
2. exact comparison of journal identity, plan digest, run/task tuple, authority digests, candidate
   order, archive prefix, and state with the Feature 153 publication journal;
3. no-follow verification of the derived batch directory and executable descriptor;
4. validation of argument, working-directory, output-root, envelope, grouping, and environment
   declarations;
5. validation of independent request, output, and wall-clock budgets; and
6. calculation of the intent, attestation, and budget digests returned in the decision.

No directory, lock, marker, journal, Store row, process registration, temporary file, archive,
state, source tree, or receipt is created or modified. No producer, evaluator, provider, or
subprocess is invoked. A failure at any point returns a fixed code without source paths,
credentials, or producer prose.

`ProducerLaunchAdmission` has status `admitted` or `rejected`, the exact immutable digests, the
derived output root, and a boolean `attestation_required`. It has no PID, process group, exit
code, score, or completion claim. An `admitted` decision is permission to perform a later exact
launch handshake, not evidence that a producer ran.

## Future process ownership and cleanup contract

The later launcher must use the existing local process ownership primitives and add a durable
launch receipt under the derived producer-batch directory. It must:

* start the executable without a shell and in a new process group;
* register the exact PID/PGID and launch-intent digest before opening a work gate;
* hold the run/task owner lock until process exit, output verification, and publication hand-off
  are complete;
* re-check the executable and owner tuple before each signal or cleanup action;
* terminate only the exact registered process group, continue cleanup for every owned resource,
  and retain evidence when cleanup is incomplete; and
* classify timeout, liveness uncertainty, output-write uncertainty, or cleanup uncertainty as
  terminal `unknown`/`recovery_required`. It must never silently re-run the producer.

Missing PID evidence is not proof of exit, and creating a second scheduler instance is not proof
that the first owner died. Recovery requires an exact launch receipt, verified owner inactivity,
and complete cleanup evidence. A later feature may implement this lifecycle without changing the
declarative intent bytes.

## Output envelope and Feature 153 interface

The producer writes into the intent's derived output root only. A successful output consists of:

1. the existing canonical `lunar-producer-result-v1` envelope at the fixed envelope path;
2. the explicit grouping descriptor required by Feature 150 when more than one material belongs
   to a candidate; and
3. the declared regular UTF-8 material files, each verified by size, SHA-256, device/inode, and
   read-race checks.

The envelope must be `completed`, carry the exact contract and producer fingerprints from the
intent, and carry a budget projection that is bounded by the intent. Producer scores and external
evidence remain provenance only. Failed, cancelled, unknown, malformed, incomplete, or
budget-inconsistent output is not an admitted bundle.

The future execution path is fixed:

```text
launch admission
  -> producer output envelope + explicit groups
  -> Feature 150 verified bundles
  -> Feature 151 native drafts
  -> Feature 152 admission plan
  -> Feature 153 publication journal and transaction
```

Feature 154 does not mutate the Feature 153 journal. A later launcher feature must carry the exact
`intent_sha256` and `attestation_sha256` into its launch receipt, and a later execution/publication
feature must bind the output envelope digest to the same journal before creating any publication
stage. A journal with a different plan, archive prefix, run/task identity, or authority pin is
rejected before launch.

## Non-goals

This feature does not launch a producer, implement a scheduler loop, create a background worker,
run a provider or evaluator, enforce remote token/cost limits, write a process or recovery
receipt, alter the Feature 153 journal schema, publish an archive, retry an unknown process, or
perform a real external campaign. It makes no quality, parity, or effectiveness claim.

## Acceptance criteria

1. Canonical intent, attestation, budget, and admission DTOs round-trip with stable digests and
   reject duplicate, unknown, oversized, credential-bearing, or non-canonical fields.
2. Admission rejects plan, journal, run/task, contract, executable byte, inode, timestamp,
   argument, output-root, grouping, and budget drift before any side effect.
3. Only an explicit one-time attestation whose run/parent-task/task tuple, intent digest, executable
   byte fingerprint, and inode identity match can authorize a future registration. The dry-run
   operation itself cannot consume or persist an attestation.
4. Request, output, and wall-clock budgets remain independent, are included in the intent digest,
   and cannot be widened by continuation or resume.
5. Dry-run/admission performs no process, provider, evaluator, Store, lock, marker, journal,
   archive, state, source, or temporary-file write.
6. The output contract accepts only the existing envelope plus explicit grouping and source
   verification required by Features 150–153; external scores never become local authority.
7. Focused provider-free tests, Ruff, compileall, diff checks, and the existing full regression
   suite pass. No external producer or historical campaign is started.
