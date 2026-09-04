# Feature Specification: Content-Addressed Local Effect Kit

**Feature Branch**: `main`
**Created**: 2026-09-04
**Status**: Implemented

## Context and scope

Features 048 and 049 can execute and score a frozen one/two-case trial, but they still require a
hand-authored suite manifest and public projection. The local Famou benchmark checkout may have a
different release label from an older experiment even when the owner has verified that the
selected case contents are equivalent. A release number alone must therefore neither block the
local experiment nor be presented as proof of byte equality.

This feature builds a deterministic trial kit directly from one or two owner-selected private case
trees. The kit derives every identity from bytes, emits only `instruction.md` and direct `data/*`
files to the subject projection, and records cross-release equivalence as an explicit owner
attestation. It does not authenticate to FM-Eval, infer an official publication digest, or turn an
owner attestation into formal benchmark evidence.

## User stories and acceptance scenarios

### User Story 1 — Build a runnable kit from local case bytes (P1)

1. The owner supplies a new output directory and one or two `KEY=/absolute/case/root` mappings.
2. Lunar validates each complete case tree with the FM-Eval-compatible `case-content-v1` rules,
   verifies the exact extractor/evaluator files, and derives a deterministic local publication,
   evaluation-profile, CaseRevision, public ledger, and harness identity.
3. Lunar writes a strict Feature 048 `suite.json`, a provenance-only `kit.json`, and a clean
   `cases/<key>/` projection containing only the official public instruction and direct data files.
4. The same bytes at another source path produce the same suite identities and output bytes.

### User Story 2 — Fail closed on unsafe or incomplete benchmark material (P1)

1. Existing output, linked/special files, unsupported case paths, missing scripts/instruction/data,
   unmaterialized Git LFS pointers, duplicate keys, unsafe keys, or more than two cases fail before
   a usable kit is published.
2. A failure cleans any adapter-created partial output without deleting a pre-existing owner path.
3. No private source path, private file, secret, or owner data value is written to `kit.json` or
   `suite.json`.

### User Story 3 — Compare historical rows using explicit owner attestation (P1)

1. When the owner confirms that historical and local selected-case contents are equivalent, the
   baseline converter records `authority=owner_attested_content_equivalent` and forces formal
   conclusion eligibility to `ineligible`.
2. The final report labels comparability as owner-attested content equivalence and adds a specific
   limitation instead of claiming an identical official publication.
3. Without the flag, strict Feature 049 baseline conversion and reporting remain unchanged.

## Functional requirements

- **FR-5001**: Add `effect-kit` CLI/library surfaces accepting exactly one or two explicit case
  mappings and a new output directory.
- **FR-5002**: Recompute the complete private case `case-content-v1` digest and reject linked,
  special, unsupported, non-NFC, case-fold-colliding, or unmaterialized Git LFS content.
- **FR-5003**: Require regular `instruction.md`, `data/`, `tests/extractor_agent.py`, and
  `tests/evaluator.py`; derive all suite digests and revision identifiers from canonical bytes.
- **FR-5004**: Copy only `instruction.md` and direct regular `data/*` files. Public ledgers MUST be
  ordered, byte-sized, SHA-256 verified, bounded, and valid under `TrialSuite`.
- **FR-5005**: A kit MUST be deterministic across source locations and MUST persist no absolute
  source paths, private files, raw data values in JSON, commands, credentials, or timestamps.
- **FR-5006**: Existing outputs MUST never be overwritten. Adapter-created partial outputs MUST be
  cleaned after failure while owner-created paths remain untouched.
- **FR-5007**: Add an explicit content-equivalence attestation option to baseline conversion. It
  MUST select a fixed authority value and formal ineligibility; conflicting authority options fail.
- **FR-5008**: Effect reports using that authority MUST use a distinct comparability kind and
  limitation. They MUST NOT claim same-publication or formal superiority.
- **FR-5009**: Existing official-suite, baseline, subject, harness, evolution, runtime, and storage
  behavior MUST remain backward compatible.

## Success criteria

- **SC-5001**: A two-case fixture produces a Feature 048-valid suite and public-only projections;
  copying the same source bytes elsewhere produces identical suite JSON.
- **SC-5002**: Private files and source paths are absent, every projected byte matches its ledger,
  and unsafe/LFS/existing-output cases fail closed.
- **SC-5003**: An attested converted baseline is accepted by EffectTrial and reports
  `descriptive_owner_attested_content_equivalent` with formal eligibility `ineligible`.
- **SC-5004**: A real current local Famou case passes kit construction and the Feature 049 exact
  harness preflight without requiring model credentials.
- **SC-5005**: Focused/full tests, lint, compileall, Specify prerequisites, and diff checks pass.

## Out of scope

- Claiming that a release label or owner statement is cryptographic proof of an older publication.
- Downloading a benchmark, exporting authenticated FM-Eval data, or mutating an FM-Eval service.
- Running a paid model when endpoint/model credentials are not explicitly configured.
- Deep-evolution comparison, full-suite parity, or statistical superiority.
