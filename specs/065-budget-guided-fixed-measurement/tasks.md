# Tasks: Budget-Guided Fixed Measurement

- [x] T065-01 Freeze protocol, identity and two isolated attempt inputs.
- [x] T065-02 Check local readiness and audit registration before execution.
- [ ] T065-03 Execute exactly two slots and preserve all outcomes.
- [ ] T065-04 Validate and aggregate observations with fixed denominators.
- [ ] T065-05 Record conclusions and limits; preserve historical evidence.

Prelaunch manifest SHA-256:
`7bc9df8abb895312a24d707afcd8aa708642472a3d9dd1515ad83c738e0abe7b`.
It freezes 35 product source files, 14 prepared attempt inputs, the campaign/attempt runners and
configuration-loader identity, exact harness Python, and historical evidence hashes. The source
import path, SDK 0.1.81/anyio 4.15.1/mcp 2.2.0 and exact private case were checked locally.
`run_campaign.py --check-only` passed with no model calls; no started marker exists at registration.
