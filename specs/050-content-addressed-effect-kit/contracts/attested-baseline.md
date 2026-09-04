# Contract: Owner-Attested Content Equivalence

Invocation extension:

```text
lunar-agent effect-baseline results.json suite.json baseline.json \
  --experiment-id fmexp-... --requested-model MODEL --effective-model MODEL \
  --model-evidence not_observable --owner-attested-content-equivalence
```

The flag means the owner has independently established that the selected historical case content
and local content-addressed kit are equivalent despite different release labels. Lunar records this
as `authority=owner_attested_content_equivalent`, forces `conclusion_eligibility=ineligible`, and
adds a report limitation. It does not verify or upgrade the attestation.

Combining the flag with a non-default `--authority` or eligible conclusion is rejected.
