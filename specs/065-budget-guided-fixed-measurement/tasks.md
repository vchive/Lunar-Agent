# Tasks: Budget-Guided Fixed Measurement

- [x] T065-01 Freeze protocol, identity and two isolated attempt inputs.
- [x] T065-02 Check local readiness and audit registration before execution.
- [x] T065-03 Execute exactly two slots and preserve all outcomes.
- [x] T065-04 Validate and aggregate observations with fixed denominators.
- [x] T065-05 Record conclusions and limits; preserve historical evidence.

Prelaunch manifest SHA-256:
`7bc9df8abb895312a24d707afcd8aa708642472a3d9dd1515ad83c738e0abe7b`.
It freezes 35 product source files, 14 prepared attempt inputs, the campaign/attempt runners and
configuration-loader identity, exact harness Python, and historical evidence hashes. The source
import path, SDK 0.1.81/anyio 4.15.1/mcp 2.2.0 and exact private case were checked locally.
`run_campaign.py --check-only` passed with no model calls; no started marker exists at registration.

Registration was committed as `cb590aa` before execution. The two slots then ran concurrently and
terminated with subject exit code 2, at 299.895 and 264.173 seconds. Bound diagnostics were both
runtime/budget_exceeded, with model/tool event counts 11/12 and 13/14. No new artifact, subject receipt,
harness or score was produced. The frozen denominator yields failed=2, valid=0, scored=0, unresolved=0;
score and unknown usage fields remain null. No retry or replacement was launched.

Offline independent audit passed: 35 source files, 14 frozen inputs, 57 historical evidence files
and 22 observed SHA links. Private case/harness and public inputs remained unchanged. A final process
check found no matching campaign runner/subject/harness command. Summary SHA-256:
`7dec7eef0b97bba8547c1ef44535259f648439a4a4884f9991311d22f5db9c9a`.

The product code was unchanged from the previously tested 667-test implementation; this turn verified
the three local launcher scripts, Specify prerequisites, and diff checks instead of rerunning that
suite. New evidence gives no observed completion improvement in these two attempts and does not
establish an individual feature's effect or identify a particular budget subtype.
