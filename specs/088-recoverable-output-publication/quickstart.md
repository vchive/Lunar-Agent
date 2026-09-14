# Offline quickstart

Run deterministic multi-output and Store fixtures:

```sh
.venv/bin/python -m pytest -o addopts='' -q \
  tests/test_output_publication.py tests/test_output_publication_store.py \
  tests/test_output_publication_concurrency.py \
  tests/test_evolved_output_materialization.py
```

Observe that a successful batch has all output rows and one promotion/commit event pair; injected
second-file or second-row failure leaves no newly published final files or output rows. Existing
identical files remain untouched. After process interruption, explicit recovery reconciles the
journal without executing a candidate. A missing materialization terminal marker still requires
diagnosis; publication recovery does not infer a successful delivery.

Repository verification:

```sh
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/ruff check src tests
.venv/bin/python -m compileall -q src tests
bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```

The active `.specify/feature.json` points to this feature. Keep the 601 tracked files under
Feature 051/074/076/078/082 unchanged; the full regression verifies their sealed evidence.
