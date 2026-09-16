# Verify and run

From the repository root at the pinned product version:

```sh
.venv/bin/python -m pytest -q tests/test_measurement120_*.py tests/test_source_check_pipeline.py
.venv/bin/python specs/112-automatic-bundle-evaluator/quickstart.py
.venv/bin/python specs/120-supported-scope-acceptance/measurement/campaign.py verify
```

Generate the manifest once with `campaign.py prepare` only after offline review. Commit and push
all registered files before `campaign.py run`. Run allocates an independent root and launches
each slot once; reusing the root fails. No old campaign is rerun on current product bytes.
`campaign.py summarize` reads outcomes and executes only available frozen evaluators against
registered synthetic holdouts. It never invokes a model, solver candidate or resume command.
Summarize writes new postrun files once; retain them without editing measured outcomes.

Each task has600-second request/process/invocation and3600-second total limits. Planned denominator
is2 regardless of failures. File count includes empty lowercase `.py` files and proves neither
imports, dependencies nor actual input use. Private response files remain local; public reports
contain only safe metadata and hashes. No new approval or attestation workflow is introduced.
