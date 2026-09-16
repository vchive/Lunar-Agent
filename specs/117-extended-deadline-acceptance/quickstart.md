# Verify and run

From the repository root at the pinned product version:

```sh
.venv/bin/python -m pytest -q tests/test_measurement117_*.py
.venv/bin/python specs/117-extended-deadline-acceptance/measurement/campaign.py verify
```

After registration commit/push, `campaign.py run` allocates its independent root and launches
each planned slot once. Reusing a claimed root fails. Do not run any old campaign on these bytes.
`campaign.py summarize` reads results and executes only available frozen evaluators on synthetic
holdout snapshots; it never invokes models or solver candidates. It writes new postrun files once.

The new request/process ceiling is 600 seconds and task wall ceiling is 3600 seconds. All other
fixed conditions match 115. Retained private responses are in each slot's `responses/` directory;
their absence is not evidence of zero provider consumption. Public reports exclude credentials
and response text. No new user attestation or approval workflow is introduced.
