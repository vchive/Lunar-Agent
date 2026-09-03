# Tasks: Private Data Profiling

## Phase 1 — tests first

- [x] T041-01 Test accurate private profiles for CSV, JSON, JSONL, and text.
- [x] T041-02 Test raw values, secrets, samples, local source paths, and content do not appear.
- [x] T041-03 Test malformed/unsupported data, duplicate headers, bounds, symlinks, and digest drift.
- [x] T041-04 Test evaluator compiler receives the profile and bundle identity binds its digest.
- [x] T041-05 Test unchanged resume reuses the profile/bundle while tampered input/profile fails.

## Phase 2 — implementation

- [x] T041-06 Implement bounded format parsers and conservative field aggregation.
- [x] T041-07 Implement descriptor/contract alignment, canonical serialization, and digest helpers.
- [x] T041-08 Add `input-profile.json` to compiler context, bundle manifest/freeze/loader, and artifact
  indexing.
- [x] T041-09 Recompute and validate the profile on compiled-evaluator resume.

## Phase 3 — documentation and verification

- [x] T041-10 Update README with structural profile fields, privacy boundary, and supported formats.
- [x] T041-11 Run focused/full tests, lint, compileall, diff, quickstart, and Specify checks; mark
  implemented, commit, and push as `vchive` on `main`.
