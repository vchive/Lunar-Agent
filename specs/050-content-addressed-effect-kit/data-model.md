# Data Model: Content-Addressed Effect Kit

## Directory layout

```text
<kit>/
  suite.json
  kit.json
  cases/
    <case-key>/
      instruction.md
      data/<direct case input files>
```

`suite.json` is the unchanged Feature 048 `TrialSuite`. `cases/` can be passed directly through
`--case-source KEY=<kit>/cases/<key>`.

## Derived identities

- `case.digest`: FM-Eval-compatible complete private `case-content-v1` digest.
- `case.revision_id`: `local-<64 lowercase digest hex>`.
- `harness`: raw SHA-256 of `tests/extractor_agent.py` and `tests/evaluator.py`.
- `evaluation_profile.digest`: canonical digest of profile name/revision plus selected case harness
  identities.
- `benchmark.publication_digest`: canonical digest of benchmark name, derived evaluation profile,
  selected case content identities, harness identities, and public ledgers.
- `benchmark.release_version`: `content-<first 16 publication digest hex>`.

## Kit provenance

```json
{
  "schema_version": "1",
  "identity_basis": "owner_attested_content_equivalent",
  "owner_attested_content_equivalence": true,
  "suite_sha256": "<raw lowercase SHA-256>",
  "benchmark": {},
  "evaluation_profile": {},
  "cases": [{
    "key": "supply_chain_inventory",
    "revision_id": "local-...",
    "digest": "sha256:...",
    "public_projection": "cases/supply_chain_inventory",
    "harness": {}
  }]
}
```

The sidecar contains no source path or raw case values.

## Attested baseline/report

The explicit baseline flag produces:

```json
{
  "authority": "owner_attested_content_equivalent",
  "conclusion_eligibility": "ineligible"
}
```

EffectTrial then emits comparability kind
`descriptive_owner_attested_content_equivalent` and limitation
`historical_publication_equivalence_is_owner_attested`.
