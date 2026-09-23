# Feature 153 quickstart

The implementation is not available yet. The intended flow is:

```text
Feature 151 ProducerBundleDrafts
  -> Feature 152 ProducerBundleAdmissionPlan
  -> immutable publication journal
  -> independent candidate execution/evaluation receipts
  -> one staged archive publication
  -> terminal journal marker
```

Resume must supply the original journal and plan. A changed bundle, authority pin, archive prefix,
receipt, or source byte must fail closed before a write.

The journal digest excludes its own `journal_sha256` field. A crash at any staging or commit point
must return `recovery_required`/`unknown` with the evidence retained; it must not infer success or
silently rerun a producer or evaluator.
