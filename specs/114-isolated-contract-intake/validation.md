# Feature 114 validation

Product change: isolated contract compiler dispatch and explicit schema guidance in
`src/lunar_evolution/conversational.py`. Existing strict parsers, general Agent loop, runtime fingerprint,
Store schema and all frozen measurement code/results remain unchanged.

## Focused validation

New compiler tests: **28 passed**. Related five-file regression: **91 passed in 32.31s**.
The actual Hermes runtime with an in-memory model receives only the isolated system and current
goal/answer, no tools, memory or transcript. Tests verify timeout, existing profile budget handling,
strict malformed/unknown-field rejection without retry, legacy subprocess/noncallable fallback,
mock bypass, ordinary tool execution, and needs_input→answer→compiled→terminal resume with exactly
two compiler calls. The automatic-bundle fixture now counts three isolated calls, including intake.

Independent review found no remaining blocking issues. It confirmed schema guidance against the
actual validators and checked that preserving the existing settings fingerprint avoids rejecting
old terminal runs that require no compilation. That fingerprint is not an implementation byte pin.

## Final validation

The Feature 112 local subprocess quickstart passed after product freeze. It delivered the 7-point
candidate from scores 1, 2, 6, 7, with one delivery copy and unchanged 1/1/1/4/4 compiler/evaluator/
auditor/Agent/candidate counts after terminal resume. Log: `/private/tmp/lunar114-quickstart.log`.
All source/tests Ruff, compileall, installed CLI, Specify prerequisites, 105 local document links
and diff checks passed. After product freeze, the full suite passed: **5517 passed, 1 skipped in
378.36 seconds**. JUnit confirms 5518 tests, zero failures/errors; the existing filesystem case-alias
test is the only skip. Logs: `/private/tmp/lunar114-full.log` and `/private/tmp/lunar114-full.xml`.
No product or test changes followed this full run. The completed repair is committed and pushed
under the user's existing instruction.

## Measurement boundary

No provider/model request was made for Feature 114. The two real Feature 113 attempts remain
frozen at product `c977eb4`, both failed, official quality null. All 113 source, tests, registration
and postrun evidence are byte-identical to `f9010c5`; older specified frozen directories remain
unchanged against `027a235`. Do not run the old campaign with repaired product bytes.

No raw failed-response retention, staged-input profiling for intake or persistent compiler usage
ledger was added. A new independently registered measurement is needed to assess real improvement.
