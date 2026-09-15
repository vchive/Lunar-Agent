# Feature 101: Exact comparison plan binding

The shared comparison ID intentionally excludes benchmark provenance. A result tied only to that
ID and the arm names can therefore validate after a same-named arm changes benchmark release or
publication digest. Bind new receipts to the complete canonical plan while preserving legacy data.

## Requirements

- A result MAY include `plan_sha256`. If the key is present it MUST contain a lowercase SHA-256,
  not null. It hashes `BenchmarkComparisonPlan.to_dict()` using the existing canonical plan digest.
- The pin participates in the result ID. With the field absent, valid legacy canonical JSON,
  result ID and digest remain unchanged.
- Admission always revalidates plan DTO structure and common-arm consistency. A receipt pin MUST
  match the supplied plan. An explicit caller `expected_plan_sha256` MUST match both the plan and
  the receipt; a legacy receipt cannot satisfy that request.
- `BenchmarkComparisonResult.from_plan(plan, arms)` explicitly creates a new pinned receipt after
  structural checks. It performs no filesystem access and is not evidence of a prior execution.
- CLI `benchmark-comparison validate-result --plan-sha256 SHA` supplies the caller pin. Report
  `plan_bound` independently of `evidence_bound` and expose the canonical `plan_sha256` checked.
- Reuse a private bounded file reader for task, plan, result and evidence files. Preserve the
  existing per-document and per-input byte limits; reject observed file/ancestor replacement.
  File paths use the 100 boundary: no symlink components or `..`, at most 4096 UTF-8 bytes and
  128 absolute components. Inputs retain their existing 16 MiB per-file limit.
- Validation remains read-only and runs before config/Store initialization. It does not launch
  frameworks, models, evaluators, providers or campaigns, or grant candidate/score authority.

The pin binds exactly the fields present in the current plan DTO, including benchmark name, release,
publication digest and their association with arm names. It does not bind unrepresented producer
commands or framework configuration, authenticate the producer, or certify measurements. The file
checks are bounded observations, not one atomic multi-file snapshot.
