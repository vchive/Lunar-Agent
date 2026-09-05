# Research Notes: Controlled Deep-Evolution Feedback Contract

## Local sources reviewed

- `深度演化 PRD` (`sqWURJ5cTnE_Z7`): deep evolution is a visible iterative experiment and should
  preserve the current best result when interrupted.
- `v2.5深度演化工具集设计` (`7bveCuILHL_BnP`): the control plane exposes narrow operations and
  bounded responses; it does not expose credentials or arbitrary platform data.
- `web agent与famou-v2深度演化打通链路梳理` (`y0gVkzefWknA6h`): progress callbacks carry task
  progress, iteration, and result state back into a fresh conversation turn.
- `深度演化阶段webagent agentic loop vs famou-2 evolve效果对比评测报告`
  (`qx9kRYpa6zTQmP`): more iterations can amplify reward hacking when the evaluator has a hole;
  adaptive problem understanding matters more than blind round count.
- `基于famou-bench-v2的深度演化阶段模型评测报告` (`YfEcoKAjskbg3P`): long responses and
  parse failures reduce effective rollout count, so feedback must remain compact and structured.

## Decisions

- Use a strict local JSON contract rather than replaying full evaluator prompts.
- Include generic numeric metrics only when their names are explicitly allowlisted.
- Include hashes and sizes, never candidate contents, in the artifact manifest.
- Treat invalidity and extraction failure as repair categories before stagnation.
- Keep the default threshold at two non-improving rounds and make it frozen/configurable.
