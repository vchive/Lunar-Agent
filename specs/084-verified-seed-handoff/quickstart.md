# Feature 084 offline quickstart

This scenario uses only temporary files, bounded fake producer output, and deterministic local fake evaluators/backends.

1. Create a manifest with one valid fake OpenEvolve-produced Python source and one missing source. Give both records `origin_kind=external`, a bounded `producer_id`, a SHA-256 `producer_fingerprint`, and an optional opaque `producer_run_id`.
2. Include an external evaluation for the valid source but no Lunar receipt. Run the seed adapter against the repository's mock exact evaluator and confirm the external evaluation is advisory only. Inspect canonical records and confirm both external evidence and external record metadata contain only `present`, `score_present`, and `payload_sha256`, with no raw score or prose.
3. Confirm every record is adjudicated before mutation and the adapter returns one admitted seed with a local evaluator receipt plus one fixed rejection reason. Confirm no partial active population is visible during processing.
4. Pass the complete admission result to local population initialization. Confirm the admitted subset is committed atomically, its receipt is persisted, then checkpoint and resume with the same contract, evaluator kind/fingerprint, source, and provenance fingerprints. Confirm the candidate ID is unchanged and does not derive from `producer_run_id`. In a separate local-origin identity fixture, confirm an allowed evaluator-kind change produces a different identity. For the external seed, changing away from the required `exact_harness` kind must be rejected before admission.
5. Change the source, evaluator fingerprint, or normalized producer declaration and resume again. Confirm a handoff mismatch before selection and no duplicate archive entry.
6. Feed a fake remote result that contains material references and an external score but no local receipt. Confirm it is retained as provenance-only. Route the synchronized material through the same seed adapter and confirm it can be admitted only after a successful matching local receipt.

The quickstart must not invoke OpenEvolve or another external evolution framework and must not contact famou-v2, WebAgent, a provider, a company platform, or a model.
