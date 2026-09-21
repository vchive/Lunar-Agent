# Feature 115 validation

## Before launch

The product remains byte-identical to `5e2568f286b709c7f8bd4c883bf654582908e736`.
The 113 campaign and its tests remain unchanged; its historical manifest is explicitly pinned at
`9f30acf0db6e672331c86a3efc46a964fb71d4c1d8a4cd2fe287ee9ec8e6e367`.

All **168** relevant offline tests passed in **4.04 seconds**: 118 existing task/guard/analysis/
supervisor cases plus 50 new registration, copied-launcher and diagnostic cases. JUnit is at
`/private/tmp/lunar115-prelaunch.xml`. The diagnostic tests check credential redaction, UTF-8
truncation, exact native arguments/return identity, usage/error preservation and advisory IO failure.
Registration tests reject any changed fixed condition, drifted historical manifest or shadowed
helper module. No test makes a provider request.

Ruff, compileall, Specify prerequisites and diff checks passed. Read-only provider inspection
confirmed the same safe metadata as 113. The product's last full suite remains **5517 passed,
1 skipped**; no product changes justify repeating it for this measurement-only increment.

115 manifest SHA-256:
`a4be47bfc2d6d02446fac1834f34ce8176a92017694cb6d71f8508e364f8a6c9`.
Preparation/verification make zero model calls. Commit and push registration before launch;
real outcomes are stored separately under `postrun/` without modifying the frozen inputs or code.

Independent prelaunch audit passed: all 76 product, 16 measurement/test and 15 historical pins
matched; all 15 fixed-condition fields matched 113; the new campaign root did not exist. No
blocking findings and no model call during the audit.

## After launch

Registration `acfb815` was pushed before either slot. Both planned attempts finished once;
primary and registered-envelope completion are 0/2. Budget selection accepted its contract then
timed out preparing the evaluator. Worker assignment timed out during contract intake. There
were three requests, one usage-bearing `glm-5.2` response and two HTTP open-response timeouts.
8625 tokens is only known usage; timeout consumption is unavailable. No candidate, frozen evaluator,
delivery, synthetic holdout, retry or replacement was produced.

Independent postrun audit verified the complete 40-file evidence inventory, all 76 product,
16 measurement and 15 historical pins, the call journals and stored contract. The single 5768-byte
private response strictly reparses to the saved contract. Product and frozen historical bytes
are unchanged. The audit independently confirmed the first slot's misleading awaiting_input state
without an actual question and absent preparation-failure event. See [the report](../../docs/history-archive.md).
