# Quickstart: Master Policy and Plan Contracts

All commands are local and require no Hermes, OpenCode, Codex, model server, or network.

## Direct answer decision

```bash
lunar-agent decide "What does SQLite WAL mode provide?" --json --home .lunar
```

Expected: `action` is `answer`, with no run or plan created.

## Create and execute a versioned plan

```bash
cat > plan.json <<'JSON'
{
  "goal": "prepare and verify a report",
  "tasks": [
    {"id": "research", "title": "Research", "prompt": "Collect facts"},
    {"id": "write", "title": "Write", "prompt": "Draft the report", "depends_on": ["research"]}
  ],
  "hard_constraints": ["keep files local"]
}
JSON
lunar-agent plan plan.json --runtime mock --json --home .lunar
```

Inspect the durable revision and status:

```bash
lunar-agent plan <run-id> --json --home .lunar
lunar-agent status <run-id> --json --home .lunar
```

## Patch and replan

```bash
lunar-agent patch <run-id> patch.json --json --home .lunar
lunar-agent replan <run-id> replacement-plan.json --json --home .lunar
```

Both commands return the new plan version and preserve older versions. Reusing an old
`base_version` fails without changing the ledger.

## Verified delivery

```bash
lunar-agent deliver <run-id> --json --home .lunar
```

Delivery succeeds only after the controller has a succeeded run, passing evaluator events, and
hashed run-relative artifacts. The JSON output is suitable for Codex/OpenClaw/Hermes parent Agents.

