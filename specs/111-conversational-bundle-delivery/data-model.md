# Feature 111 data model

## Conversational request

Existing `evolution_requested` events gain the optional `bundle_profile_sha256` only for bundle
mode. Legacy event shape is unchanged. The digest uses canonical JSON with protocol
`lunar-solve-bundle-profile-v1`: evaluator spec, sorted input descriptors, candidate argv, explicit
environment, timeout/output limits and dependency/environment pins. Profile, input-root and harness
storage paths are excluded; executable argv is still part of the authority. A bundle request
cannot resume through the single-file path or a different semantic profile.

No database schema changes are required. Existing parent `input_data` rows define the complete
input set at `data/raw/<target>`. Identical repeated rows are accepted; conflicting, stale, missing
or extra rows are rejected. The selected snapshot input map is checked against both those rows and
the current parent bytes before delivery.

## Links and selected evidence

The child stays at the parent's canonical `evolution-run` directory. Parent `evolution_linked` and
child `evolution_parent_linked` events must agree on IDs, contract and native population mode.
Directory validation rejects symlink traversal. Existing child contract, archive/state/result,
record/receipt rows and events determine the selected bundle and its verified materials.

## Parent delivery

`bundle_delivery_prepared` pins a portable `.bundle-deliveries/.bundle-delivery-*` package using its
relative path, byte-manifest SHA-256 and selected identity. The identity retains contract, candidate,
bundle, receipt and independent evaluation SHA-256 values. The portable package format is Feature
109's existing `lunar-bundle-delivery-v1` and includes complete source, outputs, inputs, contract,
harness/spec and evaluation report. Original execution/evaluation evidence remains in the child.

`bundle_candidate_delivered` records `mode=bundle`, parent/child IDs, selected identity, delivery
digest and source/report paths, output metadata, validation and final status. It uses the existing
`evolution.materialization` solve JSON slot; status uses `evolution.linked.materialization`.
The event's observation is
`evaluation-time`; copying never reruns the candidate or evaluator.

Existing parent artifact rows index every package file and manifest. Declared outputs use the
existing output publication batch keyed by the child run ID. The existing journal handles commit,
confirmed rollback and unknown publication. A prepared event allows replay to reuse a copy;
unfinished unpinned copies remain non-authoritative. A terminal event is revalidated against the
pinned copy, selected child evidence, parent inputs, artifact rows and output journal.

A per-parent file lock serializes delivery preparation/registration. The existing output publisher
retains its own lock and budget enforcement. This does not create a global transaction spanning all
controller activity, an execution attestation flow or active-process cancellation orchestration.
