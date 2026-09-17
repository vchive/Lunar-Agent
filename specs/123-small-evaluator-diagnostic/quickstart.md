# Verify and run

From the repository root:

```sh
.venv/bin/python -m pytest tests/test_measurement123_*.py
.venv/bin/python specs/123-small-evaluator-diagnostic/measurement/campaign.py prepare
.venv/bin/python specs/123-small-evaluator-diagnostic/measurement/campaign.py verify
```

Prepare is offline and only reads safe provider identity through the existing configured provider
loader. Complete review, commit and push all registered bytes before running:

```sh
.venv/bin/python specs/123-small-evaluator-diagnostic/measurement/campaign.py run
.venv/bin/python specs/123-small-evaluator-diagnostic/measurement/campaign.py summarize
```

Run allocates one new root and worker once. Max2 native model calls,600s each,1320s total including
preflight and8 predeclared holdouts (5s each) after freeze. A failure consumes the attempt; no resume
or replacement. Summarize only reads retained receipts and fingerprints and writes public metadata
once; it never executes models/evaluators. Assistant text remains private. Compare no old denominator.
