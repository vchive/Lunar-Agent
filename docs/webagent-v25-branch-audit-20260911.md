# WebAgent 2.5 分支与部署审计（2026-09-11）

## 结论

最新参考基线是 `origin/famou-v2.5/base`（`f6ad20caf8963d105fe26c96b6a30ef4dfd34859`）。它把远端 Famou v2 控制接口接入完整 `opencode` 包，并在配置中对 `evolve_create` 设置 `ask` 审批；`opencode_lite` 则从注册表移除整个 evolve 工具族。仓库构建脚本同时生成完整版、lite 版及兼容别名，因此目录名不能单独证明线上选用了哪一版。

`master`、`famou-v2.5/master-agent`、`famou-v2.5/evolve_tool` 和 `feature/or-agent` 都与最新 base 分叉，且四个 tip 的主要 `opencode` 演化入口仍是旧的本地 evolution-loop（相同 blob），不能把它们的分支名直接当成最新部署实现。`famou-v2` 路由也不是 e24 之后才出现：旧参考 `e24df2530ca770f78ebcda170ac55cc1203e4447` 与最新 base 的 `famou-client.ts` 是同一 blob；后续主要变化是工具注册、审批和显示属性。

## 16 个远程分支（相对最新 base）

计数为 `git rev-list --left-right --count BASE...TIP` 的 `base-only/branch-only` 提交数，不代表质量或内容等价。

| 分支 | tip | 计数 | 关系 |
|---|---|---:|---|
| SkillERA | `fb8174abf32b4cb9f938fa022e1c51b402a65223` | 106/5 | 分叉 |
| backup | `3b3478122e802441701f68bb63310930ed6b104d` | 98/0 | base 的祖先 |
| cc_sdk | `ad43bd129da6d35bd87a875d299277717a4ce969` | 164/1 | 分叉 |
| dev_viz | `458722bef4aa780235c40b15c7c7d2118a367ce0` | 76/2 | 分叉 |
| empower_skills | `8c1a77a1b44509bc4ef4c48c9466151563fffcab` | 67/5 | 分叉 |
| famou-v2.5/base | `f6ad20caf8963d105fe26c96b6a30ef4dfd34859` | 0/0 | 参考基线 |
| famou-v2.5/evolve_tool | `4ef5e0d354a0a24b6d2b2e1c8a8e2f5da2578c39` | 67/2 | 分叉 |
| famou-v2.5/master-agent | `3795cdcfc35cdc83f8f31873f9dc30b75a2e15da` | 67/1 | 分叉 |
| famou/memory | `dd4f542e6dc176915a18ed896158a2b2cece4728` | 94/0 | base 的祖先 |
| feature/or-agent | `565f5368502bb1a48760a34c50408706fe1f9bfa` | 67/48 | 分叉 |
| harness-eval | `8c1a77a1b44509bc4ef4c48c9466151563fffcab` | 67/5 | 与 empower_skills 同 tip |
| layered-compaction | `5197081d22d42a80ae99380833870eaf1ee30e3b` | 34/1 | 分叉 |
| master | `9ee31a0b0bdc7cbe4c16d2a44bb61d4993f6dc4b` | 67/19 | 分叉 |
| memory_card | `865a270a2e5a9ed7ddf57079f0fd76a80f538ed3` | 76/13 | 分叉 |
| multi-round | `79a8b2e580e09702f4921b6d6dc39cd905d0719a` | 100/0 | base 的祖先 |
| zwy | `86a5402e3d211fa5558fcf624c8ed3f5ecf98550` | 88/2 | 分叉 |

四个重点分支与 base 的共同祖先是 `0773e37ccfbac9df0619b78904565217c980d7ba`；没有一个 tip 是另一个的祖先，故“base 已合并全部分支”不成立。复制或重写的功能仍可能存在，需以文件树和 blob 为准。

## 构建与部署选择

`f6...:ipipe_build.sh:4-14,35-77` 明确：

- `pack_config opencode opencode_studio`：完整版，含深度演化；
- `pack_config opencode_lite opencode_lite`：精简版；
- `pack_config opencode opencode`：迁移期间的兼容副本；
- `power_skills` 单独发布，避免被所有 agent 常驻加载；
- `opencode.jsonc` 被剔除，部署真源是 `opencode.jsonc.template`；每个包写入 `BUILD_INFO`（配置名、源目录、分支、commit、时间）；镜像 Dockerfile/entrypoint 属于外部 `agentway` 仓库。

因此仓库能证明“可构建三种目录”，不能仅凭此证明 agentway 当前镜像消费了哪一个目录、实际 provider/model、预算或某次历史评测配置。`agent_configs/opencode-v2.5-base` 没有出现在该构建脚本中。

完整包的注册和审批：`f6...:opencode/opencode.jsonc.template:267-283` 插件路径为 `./tools/famou/famou.ts`，三个 solver agent 为 `ask`，`evolve_create` 为 `ask`。`f6...:opencode/tools/famou/tools/index.ts:20,29-36,50-52` 注册并检查 evolve 工具族，再交给 gate。lite 模板仍加载同一插件路径（`f6...:opencode_lite/opencode.jsonc.template:188-204`），但 `f6...:opencode_lite/tools/famou/tools/index.ts:19-41` 明确省略 evolve；lite 的 tool approval 对象为空（同模板 `:193-200`），且不存在 `opencode_lite/tools/famou/tools/evolve/` 树。

本地 harness 是另一条选择链：`f6...:harness/defaults.py:4-24` 默认 `repo/opencode`，支持 `--agent-config` 和 `none`；`run_bench_v2_5.py:573-624` 记录显式或默认配置并拒绝非 opencode 配置。`f6...:harness/installer.py:38-56,95-147` 将调用者选定目录复制到工作区，终态 `opencode.jsonc` 优先，且不按 Git 分支自动选择。因此 `agent_configs/opencode-v2.5-base` 是显式传参的本地快照（其 README `:9-12,74-84` 也写明“快照、不跟随上游”），不是最新部署脚本的默认来源。

## 深度演化迁移时间线

1. `a7fcec4d496b2473b900bbef92401ae35c3fbb08`：创建 v2.5 base 快照。
2. `1f67dcb8d90934a7161560e6be7d9df857987f56`：`evolve_tool/` 初始独立 overlay；`4ef5e0d354a0a24b6d2b2e1c8a8e2f5da2578c39` 拆分生命周期工具。
3. `882becbc2b1279ed91efc8352b906c1c60c823a9`：把快照里的 evolve 工具迁到 `agent_configs/opencode-v2.5-base/famou/tools/evolve/tools/`，加入注册和审批。
4. `1e5a2ce9b5a14e699fab933f5a3c0826ad94275f`：v2.5 demo，删除旧生产 `opencode/plugins/evolution-loop.ts`、`tools/init_evolution.ts`、旧 evolution agents/command，并加入新的 solver 与 famou 插件路径。
5. `a5accdf854b5538b04dd80792ad4a0a2ea4a92ff`：为外部 benchmark 修复文件复制，将 `opencode/famou` 整体移到 `opencode/tools/famou`；模板同步改路径。该提交的旧构建脚本仍只打包 `opencode/`（`9ee...:ipipe_build.sh:23-50`）。
6. `8f9f5c983fd6fd539597ae4a991bb74a2f4ab47f`：增加生产 `opencode/tools/famou/tools/evolve/*`、注册表和 master hook。
7. `ce2dad9862d9fd250e1d00b244426c20ad97a688`：增加直接 CLI 防护与诊断；`4e572f62b6d8cc053be8621cb96c02ce5c235379`：补齐显示属性要求。

关键修正：`e24...:opencode/tools/famou/tools/evolve/lib/famou-client.ts` 与 `f6...` 为相同 blob `bc0d81938a319fbc42400830887c307517b1d931`。最新 client（`f6...:.../famou-client.ts:62-79`）从 `/root/.config/opencode/tool-url/famou-v2` 读取运行时 URL，再通过 `famou-ctl --api-url ... --api-key ...` 调用；仓库没有证明远端算法、模型、预算或服务端版本。

## 四个重点分支的含义

- **master (`9ee...`)**：仍保留旧本地循环（`opencode/plugins/evolution-loop.ts` blob `8b3cc01...`，`opencode/tools/init_evolution.ts` blob `2442a59...`）；`/evolve` 写 `.evolution/state.md`，idle hook 继续迭代并按本地 `candidates/v*/score.json` 选择结果。它不是最新 base 的生产演化实现。
- **master-agent (`3795...`)**：新增 `agent_configs/opencode-v2.5-master/`；其 README `:54-65` 表示快照内移除了整条 deep evolution chain。分支名不等于线上版本。
- **evolve_tool (`4ef...`)**：提供七个控制工具的独立 overlay，写命令单次执行、失败为 unknown、不自动重试；构建到未跟踪的 `dist/.opencode-famou/`，需手工复制到目标项目，故不是自动进入 base 构建。
- **feature/or-agent (`565...`)**：增加 `agent_configs/opencode-or` 与 OR 集成，但仍携带旧 evolution-loop/init_evolution blob；不能据此推断已经迁到最新 evolve registry。

更老的 SkillERA/backup/multi-round 等分支可见 `webagent/runners/configs/.opencode/plugins/evolution-loop.ts`；cc_sdk 不含上述四个入口文件，不能据此断言它没有优化能力。latest base 与 layered-compaction 同时可见新生产 evolve 树和历史配置副本，需按构建脚本区分来源。

## 对后续 SDD/评测的边界

这份审计只做固定 Git blob、树和历史检查，没有运行 WebAgent、模型、远程 Famou 或公司评测平台，也没有读取运行时 URL 文件、密钥或部署仓库。仓库证据足以确定应优先研究 `famou-v2.5/base` 完整包的注册/审批和 `famou-client` 调用链；不能把某个分支名、README 或本地快照当成已部署版本，也不能从代码直接归因某次分数或“无有效解”的原因。
