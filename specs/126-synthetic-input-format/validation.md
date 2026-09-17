# Validation

## Implemented boundary

`validate_input_format` and private input profiling share `_parse_input`, which dispatches to the
existing `_utf8`/`_records` parsers. Record semantics and limits are unchanged; parser recursion and
Unicode errors now become controlled DataProfileError failures. No second parser or profile-based
business schema is introduced. The validator returns no profile or parsed values and performs no
filesystem/process work. Callers retain their existing byte limits.

Both preflight invocation modes validate every declared input in the entire suite before creating
its first workspace or invoking its first harness. This applies equally to compiler and audit
suites and expected-invalid outputs. A rejected compiler suite makes no auditor call; a rejected
audit suite starts no audit harness and creates no frozen bundle. Existing staging cleanup runs.
The fixed error includes only the controller's compiler/audit label and input-format category;
parser exceptions and contents are suppressed at the bundle boundary.

Shared compiler/auditor instructions explain the format rules, structural limits and distinction
from business semantics. JSON object versus object-array identity is deliberately not enforced.
Input field descriptions and private type/count statistics are not schemas. Nonempty probe text
and all prior probe byte/path limits still apply, even where real parsing accepts empty text/JSONL.
Source policy, output validation, independent audit, bundle identity and frozen loading are unchanged.

## Focused evidence

- Before implementation, the initial 72 tests produced **60 failures and 12 passes**, with no
  collection errors: 52 failed because the API did not exist and eight showed malformed final-probe
  inputs being allowed through preparation. Logs: `/private/tmp/lunar126-tests-baseline-count.log`.
- Final **81 new tests passed in 1.955s**. They cover real-profile/parser parity for JSON, JSONL,
  CSV and text, positive/negative structures and limits, scalar and late second-input rejection
  across both invocation modes and both roles, no premature workspace/harness, suppressed error
  context, prompt instructions, schema independence and frozen recovery. Fixtures are fresh
  synthetic code/data, not captured measurement responses. JUnit has zero failures/errors/skips.
- **240 related tests passed in 49.624s**, covering profile creation, compiler and adversarial
  audit, snapshot and candidate preflight, request/prompt protocols, automatic solve and terminal
  preparation recovery. JUnit has zero failures/errors/skips.
- The 112 quickstart still selects **7 from 1/2/6/7** and produces one delivery. Terminal resume
  leaves contract/compiler/auditor/Agent/candidate calls at **1/1/1/4/4**.
- Independent implementation review found no actionable issue. Source/test files were frozen
  before the full regression; the new tests passed Ruff and whitespace checks.

## Full verification

Command: `.venv/bin/python tools/run_tests.py --junit-dir .lunar/test-results/feature126`.
The two-stage entry point returned exit 0 and removed its temporary frozen checkout.

- Current working tree: **6526 passed, 1 skipped, 24 deselected in 426.02s**. JUnit records 6527
  tests with zero failures/errors. Only the original version-bound registration nodes are deselected.
- Fixed 5560eb9 checkout (product 519fea5): **24 passed in 15.00s**, zero skips/failures/errors.
  These are the same deselected nodes, executed unchanged against their registered product.
- All three frozen implementation/test files retain their pre-regression hashes. AST comparison
  against a9746fd confines existing definition changes to `build_private_input_profile`, `_preflight`
  and `_response_protocol_prompt`; added definitions are the shared parser, public validator and
  input-format instructions. Frozen load, envelope parsing and underlying record parsing are intact.
- Ruff across src/tests/tools, compileall, installed CLI help, Specify prerequisites and whitespace
  checks pass. All **140 local links in nine updated Markdown files** resolve.

## Historical preservation

All **1610 prior tracked spec/test files** retain their initial SHA-256. Original measurement
registrations and static analyses remain unchanged; no historical campaign slot is reopened and
no original campaign is re-registered against changed product bytes.
Read-only inventory checks match all retained file lengths/SHA-256: **125 16/16**, **123 15/15**,
**120 46/46**. No historical source, responses or prompts are published by these checks.

The full runner's fixed checkout verifies its original 77 product/14 measurement/69 history pins.
This is explicit historical regression isolation, not a claim those registration tests can use
changed product bytes. Both phases passed without weakening registration checks.

## Limits and next step

Format admission rejects the scalar-input class of defect observed in 125 before compiler probe
execution or an auditor request. It does not guarantee required business keys, value types/ranges,
task consistency, evaluator correctness or real-model success. Empty/mixed synthetic records may
be format-admissible while semantically wrong; the evaluator and independent audit still decide.
The public helper performs format validation, not every private-profile storage/identity check.

No real model, WebAgent, historical campaign or captured evaluator was executed. Historical
113/115/117/120 each remain 0/2 and 123/125 each remain 0/1, with separate denominators. Next add
bounded controller-owned local preparation failure stages/reasons, then independently register
any new real diagnostic before requests. External multi-file seeds, whole-chain cancellation and
detached operation remain deferred.
