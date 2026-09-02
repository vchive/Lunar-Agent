# Policy Decision Contract

The local `decide` command and parent-Agent integrations exchange one JSON object:

```json
{
  "action": "execute_plan",
  "rationale": "The goal has two dependent deliverables",
  "confidence": 0.92,
  "questions": [],
  "plan_id": "plan-abc123",
  "plan_version": 1,
  "evidence": ["two deliverables", "explicit verification request"]
}
```

Actions are `answer`, `ask_user`, `execute_plan`, `patch_plan`, `replan`, and `deliver`. Rationale,
questions, and evidence are bounded and sanitized. `ask_user` contains no more than four questions.
Standalone `answer` decisions do not create a run or plan.

