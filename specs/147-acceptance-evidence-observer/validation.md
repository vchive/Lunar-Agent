# Feature 147 validation

The provider-free observer is covered by `tests/test_acceptance_observer.py`. The tests exercise a
full six-stage chain, preparation-only prefix, manifest digest and fixed-budget tampering, receipt
ordering/binding, and native generation-receipt mismatch. The observer imports no provider client
and its public projection contains only bounded identities, stage outcomes, counters, and digests.

The companion `tests/test_campaign_inventory.py` covers canonical inventory, read-only audit,
changed bytes and tampered digest, symlink/FIFO refusal, oversized-file rejection and executable
material being read without execution. Initial focused observer/generation/inventory selection:
**38 passed**; initial worker/Store/AgentLoop compatibility selection: **206 passed**. Ruff for
`src tests tools`, compileall and diff checks pass. This is provider-free local validation.

The artifact/lifecycle semantic and holdout auditors, launch preflight and real provider acceptance
remain open work under the Feature 142 real-acceptance plan. Structure closure and byte inventory
do not promote preparation, primary or joint success.

Independent review then found a consumed-iterator source-binding bypass, conflation of unknown and
failed generation outcomes, raw malformed-input exceptions, and incomplete inventory mutation/fd
coverage. The hardened selection passed **58 tests** (25 observer, 14 existing generation, 19
inventory). The same worker/Store/AgentLoop compatibility selection plus these suites passed
**226 tests**. The exact focused command is in [quickstart.md](quickstart.md).
Directory fixtures inject add/remove/replace, a late write inside an already traversed directory,
open/fstat mismatch, and root replacement; entry/depth limits and descriptor release are verified.

The complete three-stage regression then passed with current **6777 passed, 1 skipped**, archived
historical **2294 passed**, and frozen registration **24 passed**, with zero failures/errors and
exit code 0. JUnit and logs are retained under
`.lunar-evolution/test-results/feature147-hardening/`.
