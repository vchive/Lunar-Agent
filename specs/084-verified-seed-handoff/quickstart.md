# Feature 084 offline quickstart

This scenario uses only temporary files and deterministic local fake evaluators/backends.

1. Create a manifest with one valid Python source and one missing source.
2. Run the seed adapter against the repository's mock exact evaluator. Confirm one admitted seed, one fixed rejection reason, and a persisted local evaluator receipt.
3. Run local population initialization from the admitted seed, checkpoint, and resume with the same contract/evaluator fingerprints. Confirm the candidate ID is unchanged.
4. Change the source or evaluator fingerprint and resume again. Confirm a contract mismatch before selection and no duplicate archive entry.
5. Feed a fake remote result that contains an external score but no local receipt. Confirm it is retained as provenance-only. Add a successful local receipt and confirm it can then be admitted.

The quickstart must not contact famou-v2, WebAgent, a provider, a company platform, or a model.
