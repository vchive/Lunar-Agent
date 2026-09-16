# Feature 112 data model

## Evaluator invocation

`compile_evaluator_bundle` and `load_evaluator_bundle` accept `invocation="candidate"|"snapshot"`.
The default retains the existing candidate-path interface and `frozen-evaluator-bundle-v2` identity.
Snapshot mode uses `frozen-evaluator-snapshot-v1` in the same manifest shape and keeps the same six
files: objective, evaluator, compiler probes, independent audit probes, input profile and manifest.
Its `FrozenEvaluatorBundle` records invocation and rejects the legacy direct evaluator call.

Snapshot source consumes the existing `lunar-candidate-evaluation-request-v1` request and emits a
strict existing `EvaluationReport` with `evaluator_id="compiled-bundle"`. Compiler/auditor envelopes
and probe declarations are unchanged. Preflight maps synthetic `data/raw/<target>` declarations
into the actual `inputs/<target>` snapshot layout, validates output formats and runs the harness
with the existing bounded process helper. It creates no candidate, execution record or receipt.

## Automatic conversational mode

An automatic request adds `bundle_mode="compiled"` to `evolution_requested` and sets its existing
`compile_evaluator` boolean. Other requests retain their previous shape. Explicit profile and
automatic modes cannot be mixed. The saved mode controls answer/resume even when no mode flag is
repeated; the usual compiler/runtime and evolution configuration checks still apply.

`automatic_solve_bundle.py` derives descriptors from the complete parent `input_data` ledger.
Identical duplicate rows are accepted; conflicting, missing, extra or changed inputs fail. The
existing private structural profile verifies all inputs against the compiled contract. Its
format/probe limits remain those of the original frozen evaluator compiler.

## Prepared profile and recovery

The ordinary `lunar-bundle-pipeline-v1` JSON is written to parent `bundle-profile.json`. Its relative
locations are `evaluator-bundle/evaluator.py` and `data/raw`; all remaining fields use the existing
pipeline schema. Local Python argv, explicit environment, timeouts and output bounds are fixed.
Automatic profiles use a 64 KiB candidate stdout/stderr cap, 256 KiB per evaluated output, and an
aggregate output cap equal to 256 KiB times the declared output count. The existing command timeout
applies to individual compiler/auditor/probe/candidate/evaluation invocations, not a single total
wall-clock deadline for the entire preparation and search.

`bundle_profile_prepared` pins parent/contract identity, semantic profile digest, raw profile
size/SHA-256, frozen evaluator aggregate digest and exact preparation artifact rows. The existing
Store indexes the six frozen files as `evaluator_bundle` and the profile as `bundle_profile`.
Their full bytes count toward the current parent artifact budget, refreshed after compilation.

A per-parent file lock serializes preparation. The profile is published through a no-clobber link
from a fully written, fsynced temporary file. A completed frozen evaluator can be loaded after
interruption without compiler/auditor calls. An interrupted artifact registration can finish using
the same profile and rows. Once a prepared event exists, any missing or changed material is an
error; a child without prepared authority cannot trigger compilation. Registered-but-missing
profile bytes cannot be silently recreated. Retained temporary compiler/preflight files are not
candidate execution or scoring authority.

Read-only validation is used before continuation mutation and in parent bundle delivery, including
ordinary `deliver`. It verifies current inputs, frozen material, profile settings, artifact rows and
prepared event. Full source/independent output delivery otherwise reuses Feature 111 unchanged.
No new database, candidate, receipt, execution or user-attestation schema is introduced.
