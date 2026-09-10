# Plan: Explicit Master Planning Role

## Decisions and alternatives

Add one private, deterministic `_master_prompt(prompt: str) -> str` helper in `staged_workflow.py`.
It concatenates a Master-role prefix, the original prompt, and a minimal-handoff/JSON suffix. Keep
`self._prompt` as the untouched original and replace only the current inline Master construction.
There is no new public API, dependency, persistent field, runtime call or mutable role state.

Use visible context labels without interpreting their contents. A task containing an identical
label is still preserved verbatim; these delimiters are human/model context, not a security boundary.
Do not rewrite the public instruction, strip its solver requirements or invent problem details.

A Master-specific system prompt would also address generic system instructions, but would enlarge
the treatment and require role restoration on success/failure/resume. Restricting tools, forcing an
inspection count, shortening the Master limit or adding a fallback plan would each alter an
independent mechanism. Defer those alternatives. Keep the present general system and budget hints
visible, and describe any real outcome as a future hypothesis test rather than proven causality.

## Implementation and verification

1. Write this SDD and failure-first native message/handoff tests before altering source. Reuse the
   existing fake GLM/native adapter/trial fixtures and capture the actual system, user and tool
   messages. Include a public task with Unicode, CRLF, JSON and delimiter-like text.
2. Add the helper and use it for Master only. Preserve the entire prior JSON/path contract and
   describe unresolved checks as future Build steps; no synthesized plan or extra invocation.
3. Verify the original prompt appears as one unmodified contiguous context and that normal/deep,
   Build/resume, systems, tool schemas, budget snapshots and aggregate ledger remain unaffected.
   Keep provider/parse/schema/path/secret failure gates and sole native harness dispatch covered.
4. Confirm imports resolve to the isolated source, run focused and adjacent tests, Ruff, Specify
   and diff checks. Report review-ready without committing or merging. The root agent owns the
   independent review, Feature 076 seal and subsequent integration/measurement decisions.

## Runnable quickstart

From the isolated worktree:

```sh
PYTHONPATH="$PWD/src" /Users/liminghan/Documents/lunar_agent/.venv/bin/python -c 'from pathlib import Path; import famou.staged_workflow as m; assert Path(m.__file__).resolve() == Path("src/famou/staged_workflow.py").resolve(); print(m.__file__)'
PYTHONPATH="$PWD/src" /Users/liminghan/Documents/lunar_agent/.venv/bin/python -m pytest -o addopts='' -q tests/test_master_planning_role_integration.py tests/test_master_plan_envelope.py tests/test_master_plan_envelope_integration.py tests/test_master_plan_vocabulary.py tests/test_staged_workflow.py tests/test_staged_effect_adapter.py tests/test_effect_adapters.py
/Users/liminghan/Documents/lunar_agent/.venv/bin/ruff check src/famou/staged_workflow.py tests/test_master_planning_role_integration.py
bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```

## Constitution review and migration

No exception. Constitution IV's independent verifier and V's actual tool/filesystem/secret/resource
boundaries remain unchanged. VI is satisfied by native-message and failure-path regressions around
the existing state machine. No migration, restart, recovery or compatibility shim is introduced.
The feature affects newly started staged Master prompts only; it cannot resume an old failed attempt.
