# Quickstart: Algorithm Problem Contract and Workspace

This validation uses the deterministic mock runtime and never contacts a model or service.

## 1. Create a contract-bearing plan

Save the example from [problem-contract.md](contracts/problem-contract.md) as
`/tmp/lunar-routing-plan.json` (or another local path), with the top-level `goal` and `tasks`
required by the existing plan command. A task can use the `algorithm_problem` object in the same
JSON document:

```bash
lunar-agent plan /tmp/lunar-routing-plan.json --runtime mock --home .lunar --json
```

The result returns a run ID. Inspect the durable projection:

```bash
lunar-agent status <run-id> --home .lunar --json
lunar-agent plan <run-id> --home .lunar --json
```

The current plan includes the canonical `algorithm_problem` object. Its run workspace contains:

```text
data/raw/
data/processed/
solve/
evaluate/
output/
evolution/
algorithm-workspace.json
```

The manifest's `contract_sha256` must equal the digest of the canonical contract in the plan.

## 1a. Use the same agent directly, as a child process, or durably detached

The contract does not depend on a parent Agent. A local owner can run the command directly. A
parent such as Codex, Hermes, or OpenClaw can launch the same command with `--json`, pass the goal
through stdin, and parse the returned run ID. For a long task, use `--detach` to return a durable
handle before execution finishes, then call `resume <run-id>` from a later process. All three forms
reuse the same SQLite ledger, plan revision, workspace, and manifest.

```bash
# Child-process JSON invocation
printf '%s' 'solve this routing problem' | lunar-agent run - --runtime mock --json --home .lunar

# Detached/resumed invocation
lunar-agent run "search for a feasible schedule" --runtime mock --detach --json --home .lunar
lunar-agent resume <run-id> --runtime mock --json --home .lunar
```

## 2. Validate rejection paths

Change the contract's input path to `../outside.csv`, remove a constraint's `source`, or set
`evolution.strategy` to `unknown`. The `plan` command must return a validation error and leave no
new run in SQLite.

## 3. Validate the report contract

Use the unit fixtures to check that an invalid report cannot carry a positive score:

```bash
.venv/bin/python -m pytest -q tests/test_algorithm.py
```

Then run the complete regression set:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests
.venv/bin/python -m compileall -q src
```

Verification on 2026-09-02: the contract-bearing CLI smoke test completed with the mock runtime,
and the full pytest suite (114 tests), Ruff, compileall, and `git diff --check` all passed.

Feature 012 only registers the contract and workspace. It does not invoke a Solver Agent,
Evaluator Agent, candidate archive, or evolution strategy; those are subsequent features. `loop`
is the planned first strategy because it is lightweight and performs well under interactive budgets;
`population` remains an opt-in follow-up when longer budgets justify diversity and archive state.
