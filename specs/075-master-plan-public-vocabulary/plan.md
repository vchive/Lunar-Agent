# Plan: Public Master Plan Vocabulary

## Decisions, alternatives and contract

Remove `_FORBIDDEN` and its four semantic checks in `workflow_checkpoint.py`: plan write/read and
expected-path write/read. Leave `_SECRET`'s pattern, plan redaction, bounded text validation,
relative-path validation, persisted schemas and authority boundaries unchanged. Replace the path
semantic filter with explicit rejection of detectable credentials on write/read. At the staged
boundary also reject expected paths containing the current nonempty model API key. Paths cannot
be sanitized by renaming because that would change the declared artifact contract. The old code
did not have this generic path-secret check; this is an explicit narrow addition, not a claim of
existing protection. Errors remain bounded and omit the offending path.

Document why ordinary words are not evidence. The contract remains bounded `plan` and
`expected_paths` to a bound, hashed Master record; the accepted textual/name vocabulary expands
without adding a field or changing a record format.

Removing only `score` would fix the observed phrase but retain the same defect for a public
evaluator, baseline heuristic, test harness or a negative statement about private credentials.
Keeping a semantic name filter would still reject ordinary output files. Adding phrase allowlists
or a model-based semantic judge would be brittle, add complexity and potentially consume untracked
resources. Use the actual schema, provenance and filesystem boundaries already in place.

## Implementation and verification

1. Add controller regressions that fail under the old filter for public plan vocabulary and ordinary
   output names, including persisted-read checks. Replace legacy word-based rejection fixtures
   with an actual invalid plan/schema, retaining all usage and failure assertions.
2. Remove the semantic filter and add the specified path-secret rejection. Keep plan write
   redaction and read credential rejection unchanged. Test generic path credentials on write/read
   and the actual model key at the staged boundary, without renaming or echoing a secret path.
   Test re-signed extra control fields, detectable credentials, invalid identity, malformed plans
   and unsafe paths so failures are not merely digest failures.
3. Exercise real AgentLoop, staged subject adapter and EffectTrialRunner with deterministic local
   model/harness fixtures. Verify permitted vocabulary reaches Build and checkpoint/resume, while
   schema/path failures never call Build/harness and failed Build cannot create a result score.
   Completed receipt validation must precede the sole fixture harness dispatch.
4. Confirm imports resolve to isolated `src`, run targeted tests and adjacent authority/recovery
   regressions, Ruff, Specify and `git diff --check`. Request independent review. Do not commit,
   merge or launch; the root agent owns integration after Feature 074 is terminated and sealed.

## Runnable quickstart

Run from this feature's isolated worktree. The root virtualenv is a development tool only;
`PYTHONPATH` explicitly selects the isolated source.

```sh
PYTHONPATH="$PWD/src" /Users/liminghan/Documents/lunar_agent/.venv/bin/python -c 'from pathlib import Path; import famou.workflow_checkpoint as m; assert Path(m.__file__).resolve() == Path("src/famou/workflow_checkpoint.py").resolve(); print(m.__file__)'
PYTHONPATH="$PWD/src" /Users/liminghan/Documents/lunar_agent/.venv/bin/python -m pytest -o addopts='' -q tests/test_master_plan_vocabulary.py tests/test_workflow_checkpoint.py tests/test_master_plan_envelope.py tests/test_master_plan_envelope_integration.py tests/test_staged_workflow.py tests/test_staged_effect_adapter.py tests/test_effect_trial.py
/Users/liminghan/Documents/lunar_agent/.venv/bin/ruff check src/famou/workflow_checkpoint.py src/famou/staged_workflow.py tests/test_workflow_checkpoint.py tests/test_master_plan_vocabulary.py tests/test_master_plan_envelope_integration.py
bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```

## Constitution review, migration and limits

No exception to Constitution IV, V or VI: independent verification, actual authority/secret/resource
boundaries and tested state transitions remain intact. No dependencies, persisted data migrations,
retry or recovery changes. Existing accepted masters without detectable path credentials load
unchanged. A previously accepted master whose output name contains a detectable secret now fails
closed; do not rename its path, rewrite its evidence or automatically resume it. The staged guard
can additionally check the live model key; the durable controller has no provider key and does not
persist one. Relaxed vocabulary does not authorize restarting an old failed attempt. Keep historical
Feature 069/073/074 files unchanged; this specification explicitly refines the word-filter
interpretation for subsequent source only.
These filesystem checks retain their documented limit against arbitrary concurrent native code.
