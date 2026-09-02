# Quickstart: Artifact Acceptance Contracts

Use an explicit subprocess Runtime Adapter that creates the declared artifact. The example is
local and requires no Hermes, OpenCode, Codex, server, or model credential.

```bash
uv run lunar-agent init --home .lunar
mkdir -p demo
printf '%s\n' '{"goal":"write a checked report","tasks":[{"id":"report","title":"Report","prompt":"create report.json","acceptance":{"all":[{"artifact_exists":"report.json"},{"json_has_keys":{"path":"report.json","keys":["summary","sources"]}}]}}]}' > demo/plan.json
uv run lunar-agent plan demo/plan.json \
  --runtime subprocess \
  --command 'sh -c '\''printf "{\\"summary\\":\\"ok\\",\\"sources\\":[]}\\n" > report.json; printf "report written"'\''' \
  --json --home .lunar
```

Copy the returned `run_id`, then inspect its auditable decision:

```bash
uv run lunar-agent status <run-id> --json --home .lunar
uv run lunar-agent events <run-id> --json --home .lunar
uv run lunar-agent deliver <run-id> --json --home .lunar
```

Changing `report.json` to malformed JSON or removing `sources` makes the run fail and causes
`deliver` to reject it. The result, prompt, and evaluation audit files remain in the run workspace
for diagnosis.
