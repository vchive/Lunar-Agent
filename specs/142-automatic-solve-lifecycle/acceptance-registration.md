# Acceptance registration manifest and seal

This document defines the provider-free registration contract used before the next automatic
multi-file acceptance attempt. It extends the existing Feature 142 plan without opening a provider,
campaign, candidate, evaluator, or generated source. The registration is one fresh
`attempt-001`; the historical Feature 139 slot remains immutable.

## Canonical manifest

`build_acceptance_registration` accepts exactly one JSON object with
`schema_version="1"` and `scope="acceptance_registration"`. The object is canonical UTF-8 JSON
(sorted keys, compact separators, no non-finite numbers) and is bounded to 128 KiB. Its
`registration_sha256` is SHA-256 over the canonical object without that field.

The manifest freezes the new registration/campaign/attempt identities, product checkpoint commit,
provider/model/runtime/API mode, entrypoint, fixed Feature 142 budgets, and the single-island
population (`islands=1`, population/offspring/rounds all `1`, exactly `12` candidate tool steps).
`attempt_id` is exactly `attempt-001`.

`product_files` is a sorted, non-empty list of `{path,size,sha256}` entries for the controlled
product source/configuration files. These entries are checked against both the pinned product
commit and the checkout during preflight; registration and seal files cannot be listed as product
files.

Task, input, evaluator and evaluator-profile materials are each declared as
`{path,size,sha256}`. Paths are relative, bounded, and free of traversal, control characters,
backslashes and colons. The declared material digest must equal its corresponding top-level task,
input, evaluator or profile digest. Material paths are unique.

`holdout_pins` contains exactly eight ordered entries. Each entry has a unique safe `holdout_id`,
its integer `ordinal`, nested `input` and `expected` material declarations, and
`max_duration_ms <= 5000`. The eight inputs and expected bytes are therefore frozen in the
registration rather than represented by bare digests.

`frozen_identities` is required and contains three non-empty, duplicate-free arrays:
`registration_id`, `campaign_id`, and `campaign_root`. Its canonical SHA-256 is stored as
`frozen_identities_sha256`; the preflight rejects any new identity that appears in these arrays.
No caller may omit this denylist or supply it later as an optional admission condition.

## Seal

`build_registration_seal` creates a canonical `acceptance_registration_seal` object that binds the
registration digest, all three new identities, the product checkpoint and the campaign root. Its
`seal_sha256` covers the seal payload. The seal deliberately does not include a preflight digest,
Git status, timestamps or mutable observations, so committing the manifest and seal cannot form a
circular dependency. The manifest and seal must be committed before launch preflight.

## Read-only preflight boundary

The filesystem/Git preflight reads the committed manifest and seal with no-follow regular-file
access, verifies their exact tracked bytes, checks the registration product material against the
pinned product checkpoint, requires a clean checkout whose `HEAD` equals the verified
`origin/main`, and confirms the campaign root is absent. It rejects symlinks, FIFOs, dirty or
unpushed checkouts, missing/untracked registration files, product-byte drift, reused identities,
and a pre-existing root. It does not create the root or write a report as an admission side effect.

A `ready` observation permits a separate caller to retain the preflight record and then launch the
sole attempt. The API itself never launches, retries, resumes, repairs, increments acceptance
counters or treats a provider-free fixture as a real result.
