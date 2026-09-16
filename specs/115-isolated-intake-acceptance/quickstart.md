# Verify and inspect

From the repository root at the registered product version:

```sh
.venv/bin/python -m pytest -q tests/test_measurement115_*.py
.venv/bin/python specs/115-isolated-intake-acceptance/measurement/campaign.py verify
```

`campaign.py run` launches the new registered campaign once, after its registration is committed
and pushed. A previously claimed campaign cannot be reopened. `campaign.py summarize` reads the
retained results and invokes only available frozen evaluators on synthetic audit snapshots; it
does not invoke models or candidates. A later product version needs another registration.

Private parsed-response diagnostics are in each new slot's `responses/` directory. They are
bounded/redacted excerpts for diagnosis, not complete raw provider responses or scoring evidence.
