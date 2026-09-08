# Effect Trial Preflight

Run the gate before invoking a real normal or deep effect trial. The subject and harness
environment names are allowlisted explicitly; values must already be set in the shell.

```bash
export FAMOU_MODEL_ENDPOINT='https://model.example/v1/chat/completions'
export FAMOU_API_KEY='provided-out-of-band'
export ANTHROPIC_AUTH_TOKEN='provided-out-of-band'
export ANTHROPIC_BASE_URL='https://anthropic.example'
export ANTHROPIC_MODEL='glm-5.2'

lunar-agent effect-preflight .lunar/famou-kit-real-001/suite.json \
  .lunar/famou-kit-real-001/baseline-agentserver.json \
  --case-source supply_chain_inventory=.lunar/famou-kit-real-001/cases/supply_chain_inventory \
  --subject-command "/absolute/lunar-agent effect-subject --model gpt-5.6-sol --max-steps 100" \
  --subject-env FAMOU_MODEL_ENDPOINT --subject-env FAMOU_API_KEY \
  --harness-command "/absolute/lunar-agent effect-harness --case-root /absolute/private-case --python /absolute/harness-venv/bin/python --extractor-env ANTHROPIC_AUTH_TOKEN --extractor-env ANTHROPIC_BASE_URL --extractor-env ANTHROPIC_MODEL" \
  --harness-env ANTHROPIC_AUTH_TOKEN --harness-env ANTHROPIC_BASE_URL --harness-env ANTHROPIC_MODEL \
  --harness-python /absolute/harness-venv/bin/python \
  --harness-import anyio \
  --harness-import claude_agent_sdk \
  --harness-package claude-agent-sdk==0.1.81 \
  --requested-model gpt-5.6-sol \
  --output .lunar/effect-preflight-real-001.json --json
```

The command must complete with `status=ready` before a trial is started. It does not call either
model endpoint and does not run the private extractor/evaluator. A ready result is not a benchmark
result and does not establish WebAgent parity; it only records that the frozen local inputs and
declared runtime capabilities passed validation at that time. The locally retained, Git-ignored
`.lunar/famou-kit-real-001/baseline-agentserver.json` is an AgentServer/company-platform historical projection
for descriptive comparison; obtain and convert matching `webagent` evidence separately for any
WebAgent-specific claim.
