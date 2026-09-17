# Verify and run

```sh
.venv/bin/python -m pytest tests/test_measurement125_*.py
.venv/bin/python specs/125-snapshot-protocol-diagnostic/measurement/campaign.py prepare
.venv/bin/python specs/125-snapshot-protocol-diagnostic/measurement/campaign.py verify
```

Prepare only reads configured provider identity locally. Complete review and push every registered
byte before any real model request. Then execute the single slot and publish results once:

```sh
.venv/bin/python specs/125-snapshot-protocol-diagnostic/measurement/campaign.py run
.venv/bin/python specs/125-snapshot-protocol-diagnostic/measurement/campaign.py summarize
```

At most two isolated requests,600s each,1320s total including preflight and eight post-freeze
holdouts (5s each). A started slot is consumed even on failure. No resume, repair, fallback or
replacement. Summarize is read-only over retained evidence and creates public result files once;
private source/responses are not published. Preserve all separate historical denominators.
