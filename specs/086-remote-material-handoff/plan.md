# Plan: Remote Material Handoff

## Technical approach

First split the existing producer admission implementation after strict envelope parsing into an
object-level helper. The current `admit_producer_result` keeps its public file-reading behavior and
delegates to that helper, so OpenEvolve/Shinka compatibility and fixed error codes remain stable.

Add `src/famou/remote_material_handoff.py` as a small adapter over the existing
`RemoteExperimentState`, `ProducerResultEnvelope`, and object-level admission helper. It validates
state status, identity pins, optional previous-state reconciliation, candidate-source material
kind, a caller-supplied bounded producer budget, and a non-empty material set. It creates a generic
envelope whose external evidence contains only bounded remote lifecycle observations. It then invokes the same
local exact-harness evaluator through the producer handoff path.

No remote module receives a transport dependency. Material reads remain descriptor-based and
digest-bound in the existing producer adapter; the bridge only supplies the already synchronized
local root. Remote state metadata is normalized by `ProducerResultEnvelope` to digest-only
evidence before seed persistence.

## Verification

Use deterministic temporary-directory fixtures for completed admission, local-score authority,
state transitions, identity drift, material integrity, and no-backend-call behavior. Add one
Shinka SQLite → exporter → generic admission integration test. Run focused tests, the full suite,
Ruff, compileall, Specify prerequisites, diff checks, and sealed-artifact checks. Do not invoke a
real remote backend, external framework, model, provider, or campaign.

## Compatibility and recovery

The old `admit_producer_result` API and producer envelope schema remain unchanged. The new helper
does not write to the remote material root; local admission uses the existing private staging and
atomic seed transaction. Unknown or failed states produce no evaluator call and no local mutation.
