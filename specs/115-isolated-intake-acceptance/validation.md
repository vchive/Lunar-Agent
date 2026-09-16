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
