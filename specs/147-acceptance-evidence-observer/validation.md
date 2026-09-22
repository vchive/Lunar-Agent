# Feature 147 validation

The provider-free observer is covered by `tests/test_acceptance_observer.py`. The tests exercise a
full six-stage chain, preparation-only prefix, manifest digest and fixed-budget tampering, receipt
ordering/binding, and native generation-receipt mismatch. The observer imports no provider client
and its public projection contains only bounded identities, stage outcomes, counters, and digests.

The companion `tests/test_campaign_inventory.py` covers canonical inventory, read-only audit,
changed bytes and tampered digest, symlink/FIFO refusal, oversized-file rejection and executable
material being read without execution. Focused observer/generation/inventory selection: **38 passed**.
The worker/Store/AgentLoop compatibility selection plus these suites: **206 passed**. Ruff for
`src tests tools`, compileall and diff checks pass. This is provider-free local validation.

The artifact/lifecycle semantic and holdout auditors, launch preflight and real provider acceptance
remain open work under the Feature 142 real-acceptance plan. Structure closure and byte inventory
do not promote preparation, primary or joint success.
