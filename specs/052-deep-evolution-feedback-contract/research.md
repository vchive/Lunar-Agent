# Research Notes: Controlled Deep-Evolution Feedback Contract

## Local sources reviewed

Source labels below describe external documents. Their original titles are retained in the
[historical archive](../../docs/history-archive.md); the document IDs remain unchanged.

- `深度演化 PRD` (`sqWURJ5cTnE_Z7`): deep evolution is a visible iterative experiment and should
  preserve the current best result when interrupted.
- `v2.5深度演化工具集设计` (`7bveCuILHL_BnP`): the control plane exposes narrow operations and
  bounded responses; it does not expose credentials or arbitrary platform data.
- WebAgent 与外部参考引擎 v2 的深度演化接入说明（描述性标签） (`y0gVkzefWknA6h`): progress callbacks carry task
  progress, iteration, and result state back into a fresh conversation turn.
- WebAgent 与外部参考引擎 v2 的深度演化对照报告（描述性标签）
  (`qx9kRYpa6zTQmP`): more iterations can amplify reward hacking when the evaluator has a hole;
  adaptive problem understanding matters more than blind round count.
- 外部参考 benchmark v2 上的深度演化模型评测报告（描述性标签） (`YfEcoKAjskbg3P`): long responses and
  parse failures reduce effective rollout count, so feedback must remain compact and structured.

## Decisions

- Use a strict local JSON contract rather than replaying full evaluator prompts.
- Include generic numeric metrics only when their names are explicitly allowlisted.
- Include hashes and sizes, never candidate contents, in the artifact manifest.
- Treat invalidity and extraction failure as repair categories before stagnation.
- Keep the default threshold at two non-improving rounds and make it frozen/configurable.
