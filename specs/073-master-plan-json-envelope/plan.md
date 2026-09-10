# Plan: Deterministic Master JSON Envelopes

## Decisions, alternatives and contracts

Add a private bounded parser at staged_workflow.py's Master text-to-object boundary. Preserve
record_usage before parsing and all subsequent semantic checks/write_master ordering. A strict
whole-object or single labelled fence rule covers the observed formatting without choosing an
arbitrary JSON substring. Reject duplicate keys/nonfinite constants using standard-library json
hooks. Do not reuse effect_adapters._parse_process_json: it searches for a first object and ignores
trailing material, permitting ambiguous responses. No dependency or persistent schema changes.

The parser contract is response str -> dict or bounded WorkflowCheckpointError. Full response
UTF8 size is checked before any extraction. Fence-line identification must account for CRLF,
spaces/tabs and all competing delimiter lines; outside brace/bracket characters are rejected.
Plain-object semantics retain their existing field/path checks. Existing plan credential redaction
is preserved; no model content is echoed by new parser errors.

## Implementation and verification

1. Write failing syntax and bounded-envelope tests in a new dedicated test module.
2. Implement the private parser and replace only the existing whole-response JSON parse/size check.
3. Add deterministic native AgentLoop/subject/trial integration: fenced plan builds a valid fixture
   candidate and uses the sole native receipt gate; ambiguous response/unsafe paths never dispatch
   Build or harness and retain usage/failure semantics. No historical solver is executed.
4. Verify isolated import paths, targeted/full tests, Ruff, Specify, diff and independent review.
   Commit/push the isolated branch. After Feature072 final audit is sealed, integrate and verify
   main imports/targeted regressions, then close SDD tasks and update handoff.

## Runnable quickstart

From the isolated worktree:

```sh
PYTHONPATH="$PWD/src" /Users/liminghan/Documents/lunar_agent/.venv/bin/python -m pytest -o addopts='' -q tests/test_master_plan_envelope.py tests/test_master_plan_envelope_integration.py
/Users/liminghan/Documents/lunar_agent/.venv/bin/ruff check src/famou tests
bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```

## Constitution review / migration

No exception. Standard-library parser only, local deterministic tests, native independent receipt
authority unchanged. No state migration, interrupted-run recovery or retry behavior is added.
The in-flight Feature072 continues using its frozen source and original parser.
