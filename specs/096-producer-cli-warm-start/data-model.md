# Data model

No persistent schema changes. Reuse ProducerResultEnvelope, SeedManifest, evaluator receipts and
canonical seed/state records. Manifest preparation retains the external root only in memory;
canonical seed admission stores its own verified copies and provenance as before.

The producer fingerprint is an explicit caller pin. Dependency and environment values retain the
generic adapter's documented source-bundle dependency and declared-protocol environment digests.
The evaluator fingerprint is computed from the exact evaluator command by the existing CLI path.
