# Plan: Budget Diagnostic Fixed Measurement

1. Prepare .lunar/real-eval-glm-5.1-budget-diagnostics-20260909 and two sibling attempt directories.
   Copy only frozen suite/profile/request/runner/public files; retain run_single.py byte for byte.
2. Refresh readiness locally without model calls. Verify exact private content/dependencies, source
   import path, endpoint identity digests and all configured fields, without recording credentials.
3. Adapt the campaign guard to reject unexpected file sets and duplicate slot identities. Adapt
   the offline summarizer to retain v2 evidence and distinguish partial from complete usage.
4. Freeze launcher, summarizer, source/input/history hashes. Run syntax, preflight and deterministic
   summary checks; independently review and commit the manifest anchor before model dispatch.
5. Dispatch the fixed pair once, retain started/terminated markers and reports, and wait for both.
6. Validate sidecars/receipts/public projection and historical hashes, publish summary/audit/results,
   record conclusions and the next evidence-supported step, and commit/push the result documentation.

## Contracts and recovery

Manifest and manifest.sha256 are created exclusively; the registered digest is also committed in
this feature. Summarizer reads that anchor and checks its own manifest-bound hash (avoiding circular
self-hashing). Any interrupted slot is unresolved, not retried; stage failures remain real samples.
The unchanged per-slot runner passes solver and extractor credentials only to their respective
subprocess environments and discards raw output. Scoring uses the existing exact private harness.

New summary adds diagnostic schema_version and optional budget, plus budget-evidence counts by
limit/state. Complete usage aggregates still depend on accepted successful subject receipts.
The manifest distinguishes unchanged prompt_variant from new diagnostic_variant; source hashes
identify the complete execution variant. No statistical or causal performance claim is planned.

## Local verification

```bash
.venv/bin/python .lunar/real-eval-glm-5.1-budget-diagnostics-20260909/run_campaign.py --check-only
.venv/bin/python .lunar/real-eval-glm-5.1-budget-diagnostics-20260909/check_summary.py
# After both terminate; never invoke the started launcher again:
.venv/bin/python .lunar/real-eval-glm-5.1-budget-diagnostics-20260909/summarize.py --check-only
```

Product implementation already passed 726 tests in Feature 066. This feature verifies changed
local scaffolding, Specify and diff checks; no dependency, storage migration or constitution exception.
