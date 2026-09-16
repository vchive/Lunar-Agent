# Feature 113 validation

## Before launch

Product code and pyproject remain byte-identical to `c977eb4da528cb1ab2a98958cf0b54a01869d347`.
No historical 051/074/076/078/082 measurement files changed against `027a235`.

All **118** measurement tests passed in **2.45 seconds** (JUnit `/private/tmp/lunar113-prelaunch.xml`):
66 task/oracle cases, 20 runtime accounting cases, 13 analysis cases and 19 runner cases. Tests
include real local short subprocesses and evaluator snapshots, with no model/provider call.
Ruff, compileall, installed CLI and Specify prerequisites passed; `git diff --check` passed.

The existing Feature 112 local quickstart also passed again: scores 1, 2, 6, 7 and identical
compiler/evaluator/auditor/Agent/candidate counts 1/1/1/4/4 before and after terminal resume.
Its local root is `/private/var/folders/kt/ygjlhpbx6sq1mk2912c3fzt80000gn/T/lunar-auto-bundle112-6o2xk9x7`.
The product's full baseline remains 5371 passed, 1 skipped; no product change warrants repeating
that full suite for this measurement-only increment.

Independent prelaunch review identified and verified corrections for interrupted/unstarted slot
accounting, conditional official quality, same-input score comparisons, committed source checks,
shared usage and descendant process cleanup. No remaining blocking findings.

Registered manifest SHA-256:
`9f30acf0db6e672331c86a3efc46a964fb71d4c1d8a4cd2fe287ee9ec8e6e367`.
Registration and verification performed zero provider requests. Real outcomes belong in `postrun/`
and do not alter preregistered source, tasks, holdouts or conditions.

## After launch

Both registered slots ran once and failed at contract intake; no evaluator/candidate/delivery
was created. Known reported usage is 15958 tokens across exactly two completed GLM-5.2 responses.
Read-only analysis gives primary and envelope-qualified completion 0/2, with null quality/gap.
The manifest is byte-identical to preregistration `10b844b`.

Independent postrun audit verified all 76 product pins and 12 measurement/test pins, the complete
34-file evidence inventory, six Store artifact rows, both call journals and failure events.
There were no retries, pending requests or remaining observed processes. Frozen historical files
and product bytes are unchanged. See [the report](postrun/report.md) for the failure distinctions
and confirmed next repair; the raw responses are unavailable, so their precise contents are unknown.
