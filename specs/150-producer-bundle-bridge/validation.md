# Feature 150 validation

This feature is validated offline with local temporary regular files. The focused suite covers a
valid multi-file group, canonical ordering and digest metadata, no filesystem writes, undeclared
paths, duplicate/reused paths, entrypoint and ID validation, contract/fingerprint/producer-ID
mismatch, unsupported material kind and non-completed status, and changed source bytes. Related
producer and candidate-bundle suites preserve existing single-file behavior.

The focused command completed **265 passed**:

```sh
.venv/bin/python -m pytest -o addopts= -q --disable-warnings \
  tests/test_producer_bundle_handoff.py \
  tests/test_producer_handoff.py tests/test_seed_handoff.py \
  tests/test_candidate_bundle.py tests/test_candidate_bundle_files.py \
  tests/test_candidate_bundle_cli.py
```

Ruff, `compileall`, and `git diff --check` passed. The full repository regression completed
**7249 passed, 1 skipped** (76 warnings). A public-import smoke test and the six-file SDD
presence check passed, and a repository scan found no occurrence of the retired project name. No
provider, producer, evaluator, campaign, WebAgent comparison, or real effect measurement was run.

The bridge does not invoke a provider, producer, evaluator, campaign, remote service, or
generated source. It does not establish model effectiveness or framework parity. Before release,
run the focused tests, related producer/bundle tests, Ruff, compileall, diff checks, SDD/link
checks, and the repository old-name scan. The separate launcher/population integration remains
out of scope until a new SDD authorizes it.
