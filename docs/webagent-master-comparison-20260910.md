# WebAgent master semantics and Feature 069

Read-only comparison on 2026-09-10. WebAgent source is pinned to
`e24df2530ca770f78ebcda170ac55cc1203e4447`, previously fetched at `origin/famou-v2.5/base`.
Lunar's measured product source remains `80f5af10f4a25dab5c5aa2ad767e3b78994f34a3`.
No WebAgent, model, generated command or new benchmark attempt was executed for this review.

## Findings

| Boundary | Lunar Feature 069 | Pinned WebAgent v2.5 base |
| --- | --- | --- |
| Master completion | Must return validated `plan`/`expected_paths` JSON before Build can start | Writes a planning artifact and dispatches specialist agents |
| 300-second meaning | Registered hard master-invocation limit; model timeout terminates this subject | Default `agent_wait` timeout; the child continues running when the wait returns |
| Role | Original normal task plus appended planning instructions, same local tool registry as Build | Coordination, with data discovery/cleaning and solver roles delegated |
| Permissions | Same available tools as Build | Master still has bash/edit/write; its role text is not a read-only capability boundary |
| Solver input | Original public task plus validated master plan | Specialist solver works from separate planning/data artifacts |

The actual agent configuration matters more than the README's historical mention of a simple
`famou-build` role. The pinned snapshot has master, data-discovery, data-cleaner, OR/ML/general
solver and evaluate roles. Importing that multiagent architecture wholesale would add substantial
scope to Lunar and is not required to fix the observed UTF-8 preview defect.

## Reproducible source references

The WebAgent repository is local at
`/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/webagent`. Read the pinned blobs with
`git show e24df2530ca770f78ebcda170ac55cc1203e4447:<path>`:

- `agent_configs/opencode-v2.5-base/agents/famou-master.md`, lines 109–157: planning artifact and
  task dispatch, with model role instructions to delegate data inspection and solver work.
- `agent_configs/opencode-v2.5-base/opencode.jsonc`, lines 114–138: actual master tool permissions.
- `agent_configs/opencode-v2.5-base/famou/tools/multiagent/config.ts`, line 62: default wait=300.
- `agent_configs/opencode-v2.5-base/famou/tools/multiagent/tools/agent_wait.ts`, lines 41–70:
  bounded wait and still-running outcome.
- `agent_configs/opencode-v2.5-base/agents/famou-or.md`, lines 13–24: solver responsibilities and
  foreground execution guidance.
- Lunar `src/famou/staged_workflow.py`, lines 153–193 at the measured commit: the shared master
  tool loop, JSON plan contract and explicit master timeout before Build.

## What the real measurement supports

Feature 069 slot 2 did not finish its master phase within the registered 300 seconds. It completed
15 model responses and 19 tool calls, including three tool errors, but never entered Build or
continuation. This demonstrates a failure of this particular bounded planning attempt. It does
not measure solver quality or continuation effectiveness.

The existing high-scoring platform records establish an AgentServer/OpenCode family and model
identity; they do not prove that this specific WebAgent commit or orchestration configuration
produced those records. The comparison therefore cannot explain failure as simply “Lunar did not
copy WebAgent,” and cannot promise that copying these roles would solve the case.

After the four registered outcomes finish, candidate hypotheses include a more focused master
role and an explicit minimal planning handoff. Each requires a separate SDD and preregistration.
The ongoing campaign keeps its deadline, workflow, source and fixed denominator unchanged.
