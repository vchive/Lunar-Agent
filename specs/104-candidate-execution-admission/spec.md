# Feature 104: Candidate execution admission

## Status

Implemented (2026-09-16). The immutable DTOs, canonical path-free digest, structural pin checks,
optional bounded no-follow input verification, static CLI dispatch, and installed-CLI side-effect
fixture are complete. This feature still grants no permission to start a process.

## Problem and scope

Feature 103 produces a private workspace and a path-free runner plan, but it does not say which
inputs, dependency identity, environment identity, evaluator, or output contract a future runner
is authorized to use. A multi-file candidate must have one immutable execution declaration before
any process is started. This feature defines that declaration and its read-only admission checks.

Admission consumes an already validated `CandidateWorkspacePlan` and returns a path-free,
content-addressed execution authorization. It does not start a runner, import candidate code,
resolve packages, inspect the host environment, evaluate outputs, create a Candidate, write a
receipt/archive, initialize Store/home, or grant recovery permission.

## P1 acceptance scenarios

1. A valid workspace plan plus explicit input descriptors, dependency pin, environment pin, exact
   evaluator pin, output contract, and physical budget produces one canonical admission digest.
   Reordering inputs or environment entries does not change the digest; changing any bound field
   does.
2. A plan, bundle, contract, evaluator, dependency, environment, or output-contract mismatch is
   rejected before any local workspace or input file is opened. A caller pin can require an exact
   plan or admission digest.
3. Input descriptors are revalidated as bounded, no-follow, relative logical destinations with
   declared size and SHA-256. The admission path verifies supplied bytes under a caller-owned root
   without following links and rejects missing, changed, oversized, or replaced files.
4. The admission contains no local absolute path, command output, secret, raw input, source body,
   dependency installation result, or host environment value. It stores only explicit identities,
   limits, and digests.
5. Replaying the same canonical declaration is idempotent in memory. Admission is not a receipt
   of execution: a valid result does not imply that a process ran or that an evaluator accepted
   the candidate.

## Frozen contract

Schema `1` uses protocol `lunar-candidate-execution-admission-v1`. The top-level object contains
exactly `schema_version`, `protocol`, `workspace_plan_sha256`, `bundle_sha256`, `contract_sha256`,
`inputs`, `dependency_sha256`, `environment_sha256`, `evaluator`, `output_contract_sha256`,
`budget`, and `admission_sha256` only when serialized as a returned result (the self digest is
never an input to its own digest).

`workspace_plan_sha256`, bundle, contract, dependency, environment, evaluator fingerprint, and
output-contract digests are lowercase SHA-256 values. The plan digest must be the canonical digest
of the complete Feature 103 plan, including command, limits, and explicit environment. The bundle
and contract fields must agree with the referenced plan; callers may additionally require exact
pins for each identity.

`inputs` is a sorted list of 0--64 descriptors. Each descriptor has a canonical relative POSIX
`target`, a non-empty source label, a size bounded by the existing input ceiling, and a SHA-256.
The target is interpreted inside a future runner-owned input namespace, never as a host path.
Input source labels are opaque, bounded identifiers and do not contain local separators, secrets,
or source-machine paths. Duplicate targets and case-folded aliases are rejected.

`dependency_sha256` and `environment_sha256` are explicit caller-supplied identities. They are
opaque commitments: admission does not inspect package managers, import closure, interpreters,
container images, environment variables, GPUs, network access, or host state. An all-zero digest is
not a meaningful default; callers must provide a real declaration or use a separately specified
`empty` identity digest.

`evaluator` contains a non-secret `kind` and a lowercase fingerprint. The kind is descriptive and
cannot carry credentials, URLs, shell syntax, or a score. The fingerprint binds the exact evaluator
contract and implementation identity supplied by the caller; it does not execute or authenticate
the evaluator. `output_contract_sha256` is optional only for source-only execution and otherwise
must identify the independent output schema that a later evaluator will check.

`budget` contains positive finite `timeout_seconds`, `max_output_bytes`, `max_input_bytes`, and
`max_processes` within fixed feature ceilings. A future runner must pass these limits explicitly;
the admission layer never inherits process limits or ambient environment settings.

## Error and side-effect boundary

Public failures use fixed `candidate_execution_*` codes, including `invalid`, `too_large`,
`plan_mismatch`, `bundle_mismatch`, `contract_mismatch`, `input_invalid`, `input_missing`,
`input_changed`, `input_unsafe`, `dependency_mismatch`, `environment_mismatch`,
`evaluator_mismatch`, `output_contract_mismatch`, `budget_invalid`, and `identity_mismatch`.
Errors do not include command arguments, local paths, input contents, or environment values.

The static parser and structural validator perform no filesystem IO. Byte admission is bounded and
read-only, uses the existing descriptor-based no-follow reader, and checks file identity before and
after each read. It runs before normal configuration/Store initialization. No process, shell,
import, package resolver, evaluator, provider, scheduler, archive, receipt, ledger, or recovery
operation is allowed.

## Limits and non-goals

This feature does not execute a candidate or prove dependency/environment authenticity. It does
not define an input staging layout, evaluator report schema, output publication transaction,
Candidate conversion, exact-once launch, resume policy, or external framework adapter. Those are
separate features that must consume this admission as an immutable input.
