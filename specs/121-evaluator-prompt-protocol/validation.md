# Validation

## Implemented boundary

Only evaluator prompt construction changes in the product. Shared examples and instructions now
cover exact envelope/probe/report fields, source restrictions, both invocation layouts and
schema-valid negative business probes. Existing parser, source validator, coverage/preflight,
isolated model calls, frozen manifests, input hashes and resume paths remain unchanged.

The two new test files total **51 passing tests** (34 prompt protocol + 17 request diagnostics),
JUnit zero failures/errors. The diagnostic rejects changed journals, contracts, inputs, response
captures and altered evidence inventories, without provider/network access or private text output.

No real model call in 121. Frozen113/115/117/120 results remain separately 0/2; no model, evaluator
or candidate is replayed in the historical request analysis.

## Offline evidence

The diagnostic extracts registered120 source from local Git and reconstructs all four historical
request hashes exactly. The old evaluator request sizes were 9,723/11,366 bytes; contract/profile
occur once each, with exactly system+user messages, no tools/history and no application retry.
The new prompts add explicit protocol details; constructing requests with the same inputs yields
17,058/18,734 bytes, without sending them. There is no demonstrated latency gain or known timeout
cause. See [diagnostics](../../docs/history-archive.md).

Prompt protocol tests: 34 passed, including actual snapshot/legacy preflight on filled examples,
strict report parsing, source coverage, read operations/import restrictions, and conservative
string-literal rules. Earlier focused evaluator/source/preparation regression: 181 passed in 24.329s,
JUnit zero failures/errors; 5 final literal tests subsequently passed in the 34-test prompt suite.

Local 112 quickstart delivered 7 from 1/2/6/7, retained compiler/evaluator-compiler/evaluator-auditor/
Agent/candidate call counts 1/1/1/4/4 across terminal resume, and produced one delivery copy.
Ruff, compileall, installed CLI help, Specify prerequisites and whitespace checks passed.

Independent product review found no blocking issue; it confirmed no parser/runtime/frozen-identity
change and no compiler self-probe leakage into the auditor. Final checks after implementation freeze are recorded below.


## Final verification

- Full regression: **6049 passed, 1 skipped in 403.54s**. JUnit reports 6050 tests, zero errors
  and zero failures. Command: `.venv/bin/python -m pytest --junitxml=/private/tmp/lunar121-full.xml`.
- Implementation/tests/diagnostic report hashes remained unchanged after freeze. An AST comparison
  against 566fbb6 confirms only `_compiler_prompt` and `_auditor_prompt` changed among existing
  product definitions; five shared prompt/example helpers were added.
- Historical audit: 46 earlier campaign pins, all 15 tracked 120 files and all 46 retained 120 evidence
  files matched their original bytes/size/SHA. No history verifier was rerun on new product bytes.
- All 128 local documentation links resolved; Ruff, compileall, installed CLI and Specify checks
  passed. Independent product review and diagnostic verification passed.
- Diagnostic report SHA256: `ddc724648b70e56417680fecaeb1cebdcd343f94f08e013c7ef9b412ef050d9e`.

Local logs: `/private/tmp/lunar121-new.log/.xml`, `/private/tmp/lunar121-focused.log/.xml`,
`/private/tmp/lunar121-quickstart.log`, `/private/tmp/lunar121-full.log/.xml`, and frozen hashes in
`/private/tmp/lunar121-freeze.json`. These paths are local validation logs, not portable run artifacts.
The feature is ready for the authorized normal commit/push; no new real-model outcome is claimed.
