# Validation

## Focused evidence

- Core DTO/parser/identity tests: 84 passed. Tests were first run before the module existed and
  failed on import; implementation then passed them.
- Independent filesystem tests: 45 passed. Cover bounded manifest/source reads, missing and
  non-regular nodes, symlink ancestors, directory/file replacement, same-size modification,
  growth/deletion during reads, descriptor cleanup and unchanged source bytes.
- CLI integration tests: 30 passed. Cover JSON/text output, optional bundle pin, contract and
  bundle mismatch, modified helper source, malformed/linked/FIFO/oversized inputs, fixed errors,
  no config/Store initialization, no candidate execution and no source text/path disclosure.
- Combined Feature 102 and all benchmark tests: **346 passed in 0.73s**.
- Independent final review: no blocking findings in core, CLI, exports or documentation.

The installed `.venv/bin/lunar-agent` ran the exact quickstart fixture: two files / 131 source
bytes validated; a same-size helper modification failed with `candidate_bundle_source_changed`;
home and the source execution marker remained absent. Bundle digest was
`d3ae1c7ac6eef7b047734a16bdd12a9810441e23c132636b7f6b9936b4196935`.
Fixture retained at `/private/var/folders/kt/ygjlhpbx6sq1mk2912c3fzt80000gn/T/lunar-source-bundle-bocdo9dm`.

## Final checks

Full regression: **4169 passed in 202.02s**. JUnit at
`/tmp/lunar-feature102-regression.xml` confirms 4169 tests and zero failures/errors/skips. Whole
src/tests Ruff and compileall passed. Specify prerequisite check passed. Historical
051/074/076/078/082 measurement directories contain 601 tracked files, unchanged relative to
`027a235`. Final staged diff check passed, including all new files. Local `main` commit only; no push.

This feature used offline fixtures only; no real framework, model, provider, WebAgent, remote
service or campaign was run. No algorithm effectiveness conclusion follows from these checks.
Existing single-file Candidate, SeedManifest, producer, evaluator and persistence schemas are
unchanged. Bundle verification remains a per-file observation, not an atomic repository snapshot,
dependency/environment attestation or execution/evaluation admission.
