# Development quickstart

Feature 148 has no implementation or new runnable auditor yet. Its prerequisites can be checked
without contacting a provider:

```sh
./.venv/bin/python -m pytest --disable-warnings -ra tests/test_acceptance_observer.py tests/test_candidate_generation_receipt.py tests/test_campaign_inventory.py
```

Implement [tasks.md](tasks.md) in order using fresh local fixtures. Use the native read-only
execution, evaluation and delivery inspectors; do not execute historical candidate material or
rewrite an inode-bound receipt to make a relocated directory pass. Record the actual auditor API,
usage example and verification results here after implementation.
