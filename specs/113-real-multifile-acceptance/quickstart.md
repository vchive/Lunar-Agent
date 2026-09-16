# Reproduce the checks

From the repository root, run:

```sh
.venv/bin/python -m pytest -q tests/test_measurement113_*.py
.venv/bin/python specs/113-real-multifile-acceptance/measurement/campaign.py verify
```

The registered real campaign is launched once with `campaign.py run`. It requires the pinned
provider configuration and committed/pushed registration. Repeating that command refuses to
reopen the campaign. `campaign.py summarize` only analyzes retained results and does not invoke
a model or rerun a candidate. A new measurement needs a new registration.
