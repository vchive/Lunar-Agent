# Quickstart: one-shot artifact output

For an OpenAI-compatible endpoint, structured task prompts allow this response:

```json
{
  "text": "Route table generated.",
  "artifacts": [
    {"path": "output/routes.csv", "content": "order_id,route_id\n1,r1\n"}
  ]
}
```

The file is written to the task's private workspace, validated by `OutputSpec`, then promoted and
hashed by Lunar-Agent. Tool calls still require `--agent-loop`; the envelope is the bounded
one-shot alternative for models that can return structured JSON but cannot execute tools.
