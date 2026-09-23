# Feature 151 data model

```text
ProducerBundleDraft
  bundle_id: explicit producer group identifier
  draft: CandidateDraft(source_files=..., filename=entrypoint)
  bundle_sha256: canonical CandidateSourceBundle digest
  producer_fingerprint: pinned producer identity
  producer_id: optional producer identity
  envelope_sha256: optional producer envelope digest
```

The nested draft metadata contains only the same provenance projection. It carries no external
score or evaluator result.
