# Offline quickstart

Run the observer tests without network access or provider credentials:

```sh
./.venv/bin/pytest --disable-warnings -ra tests/test_acceptance_observer.py tests/test_candidate_generation_receipt.py tests/test_campaign_inventory.py
```

The helper `build_acceptance_manifest` creates a canonical **observation manifest draft**.
`observe_acceptance_evidence` accepts only that manifest and in-memory stage receipts. It does
not read a campaign directory, launch a request, execute generated source, run an evaluator or
holdout, resume a task, or mutate Store state. A structurally complete chain reports
`status=chain_complete` and `validation_scope=receipt_chain_only`; it still reports
`primary_success=0/1` and `joint_success=0/1`.

`inventory_campaign_directory(root)` produces the canonical byte inventory for a quiescent retained
directory. Store the returned record outside that directory. `audit_campaign_directory(root, record)`
recomputes the inventory and returns a bounded verified projection only when every retained byte
still matches; it does not prove the semantic success of any stage.
