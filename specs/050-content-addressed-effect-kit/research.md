# Research: Content Identity and Release Labels

## Verified source facts

- The current local `agentco-bench-lite` checkout declares `1.10.25`; its Git history did not carry
  an immutable `1.10.6` publication manifest before the benchmark publication tooling landed.
- The owner explicitly confirms that the relevant uploaded content is equivalent and does not want
  the local experiment blocked on the release number.
- FM-Eval `build_case_package` defines `case-content-v1` from path, role, media type, normalized
  mode, size, and content digest. Lunar's implementation matches the SDK on ASCII and Chinese-name
  real cases.
- FM-Eval's SUT-readable projection is only `public_instruction` and `public_case_input`, which map
  to `instruction.md` and direct `data/*` files.
- Feature 048 already marks every small trial formally ineligible. Its baseline `authority` is a
  bounded identifier and can preserve an owner-attestation evidence level without a schema change.
- No model endpoint, model key, or extractor credential is configured in the current shell, so a
  real model trial cannot be honestly executed during this feature.

## Alternatives

| Alternative | Decision | Reason |
|---|---|---|
| Guess historical publication identity from Git | Reject | Release metadata was added later and does not prove the old online snapshot. |
| Require online FM-Eval for every kit | Reject | Breaks standalone/local operation and the current browser cannot access the internal HTTP page. |
| Ignore all identity metadata | Reject | Makes score comparison unauditable and weakens the exact harness boundary. |
| Derive a local content-addressed suite | Select | Reproducible from bytes and independent of path/version labels. |
| Label derived suite as official 1.10.6 | Reject | Owner confirmation is useful evidence but not a platform publication digest. |
| Record explicit owner-attested equivalence | Select | Matches the user's knowledge while keeping formal claims honest. |

## Real-case selection

The feature should preflight `supply_chain_inventory` because it is compact, materialized, and its
canonical digest has already been independently matched to the FM-Eval SDK. That preflight proves
kit compatibility only; without a configured model and historical result export it is not a score.
