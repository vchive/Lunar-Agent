# Read-only result audit and report

The campaign completed on 2026-09-10. Its final audit, report and process observation were sealed
in commit `26fc4a4` before the reviewed 070/071 tool fixes were merged. See [results.md](results.md),
[final-audit.json](final-audit.json), [final-report.md](final-report.md) and
[final-process-check.json](final-process-check.json). Current product source now includes those
fixes, so running the original live-source audit commands below must reject the changed source.
The commands document the pre-integration audit; do not rewrite the manifest to make them pass.

These analysis tools were added while the registered Feature 069 campaign was running. They are
outside its frozen `measurement/` dispatcher directory and do not change product source, tools,
inputs, budgets, attempt counts or launch behavior. They never load provider configuration,
execute a subject/harness, repair a record, or write a campaign artifact.

## Read a current observation

From the repository root:

```sh
.venv/bin/python specs/069-webagent-normal-workflow/postrun/audit.py \
  specs/069-webagent-normal-workflow/measurement/manifest.json \
  .lunar/real-eval-glm-5.2-staged-20260910
.venv/bin/python specs/069-webagent-normal-workflow/postrun/render_report.py
```

The JSON audit includes `passed`, `complete`, the native summary, observed evidence SHA256 values
and the analysis script's own digest. `passed=true, complete=false` means the observed partial
evidence is consistent; it does not approve a completed experiment. Both commands write only to
stdout. A concurrent phase transition can invalidate a snapshot; read again without repairing or
restarting anything.

The renderer validates `reference.json` against the actual historical files already pinned in the
registration. It preserves the three platform scores for each case and the prior Lunar observation,
including null. These records never enter the current four-slot denominator. Native scores above
one are preserved, and different cases are not pooled into a mean.

## Require final evidence

Use the same audit command with `--require-complete`, and render with:

```sh
.venv/bin/python specs/069-webagent-normal-workflow/postrun/render_report.py --require-complete
```

Final acceptance requires all four outer termination markers, campaign termination and an existing
final summary identical to the native reconstruction. Checks include:

- Registration committed before dispatch, the original implementation's Git blobs and all frozen
  and historical hashes, plus the actual imported package path.
- Original public projections, actual private case content and exact harness identity through the
  frozen worker binding checks.
- Four prescribed slots, no extra case/run/attempt, phase start/termination/request bindings and
  accepted native record/state/report/outcome links. Accepted receipts are reparsed through native
  validators; no backup restoration code is called.
- Both first-wave terminations before any second-wave start. Since outer end markers store elapsed
  time rather than end timestamps, the audit uses start wall time plus monotonic elapsed time with
  a disclosed two-second consistency tolerance. This is a postrun check, not an added runtime budget
  or evidence of precise per-tool latency.
- Partial observations remain explicitly incomplete; unscored and failed extraction observations
  keep null scores rather than harness placeholder zero values.

After final acceptance, save the audit and rendered report as new files using exclusive creation.
Independently review the results, confirm the campaign processes have terminated, update T069-07
and HANDOFF, then integrate the already reviewed Feature 070/071 branches. This auditor does not
probe process liveness. It cannot accept a new implementation as the measured source: after those
fixes are integrated, retain the sealed audit and original Git/hash evidence instead of rewriting
the old manifest to make a current-source check pass.

## Offline tests

```sh
.venv/bin/python -m pytest -o addopts='' -q specs/069-webagent-normal-workflow/postrun
.venv/bin/ruff check specs/069-webagent-normal-workflow/postrun
```

Tests are kept alongside the analysis tools so the campaign's frozen `tests/` file set is unchanged.
They cover timing, extra attempts, changed evidence, partial/final boundaries, historical-reference
tampering, unknown scores and report wording. Fixtures are temporary and do not invoke a model.
