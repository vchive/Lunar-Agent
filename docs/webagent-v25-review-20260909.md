# WebAgent 分支审查与 Lunar 移植决策

审查日期：2026-09-09。已执行 `git fetch origin`，不切换或修改 WebAgent 工作树，也未运行
WebAgent、公司评测或真实模型调用。先盘点全部远端分支，再深入下面与 Lunar 有关的实现；
不是对全部分支逐行审计。代码路径均相对于本机 WebAgent 仓库。

## 1. 固定来源，避免把分支名当作版本先后

| 分支 | HEAD | 本轮关注点 |
| --- | --- | --- |
| `famou-v2.5/base` | `e24df25` | 当前合版；工具契约、预算指导、worker 生命周期、结果存储 |
| `master` | `9ee31a0` | 9 月 8 日重新合入记忆卡片 |
| `layered-compaction` | `5197081` | 9 月 7 日上下文压缩迁移 |
| `memory_card` | `865a270` | 记忆检索隔离和结构化卡片 |
| `famou-v2.5/master-agent` | `3795cdc` | 8 月 28 日角色/skill 合版历史 |
| `famou-v2.5/evolve_tool` | `4ef5e0d` | 8 月 27 日演化工具拆分历史 |
| `feature/or-agent` | `565f536` | OR 求解角色和领域 skill 历史 |
| `famou/memory` | `dd4f542` | 旧 shared-context 路径 |
| `multi-round` | `79a8b2e` | 旧多轮实现，本轮只核对历史 |
| `SkillERA` | `fb8174a` | 旧技能演化实现，本轮只核对历史 |

其余 `cc_sdk`、`backup`、`dev_viz`、`zwy`、`empower_skills`、`harness-eval` 已盘点，
不作为本轮求解 runtime 移植来源。不能把不同分支所有功能都称为“v2.5 已上线”。

拉取前的 base 为 `465af9d`，拉取后为当天的 `e24df25`。新增变更包含演化默认配置简化、
`evolve_create` 失败处理、CLI 入口防绕过和可视化规范拆分。最新 `base` 才有
`opencode/tools/famou/shared/result.ts`、`tools/multiagent/lifecycle/settle.ts` 等路径；
不能把这些路径归给较旧的 `evolve_tool` HEAD。

## 2. 已吸收：工具参数说明必须出现在最终模型请求

来源：`famou-v2.5/base` 的 `opencode/tools/famou/shared/param-description-fix.ts`。
`ee5d524` 记录的实际问题是 OpenCode 1.3.10 和插件使用不同 Zod 实例，导致参数类型与
required 仍在，参数 description 丢失。修复从原 schema 取说明，借宿主实例重新包装，
同时恢复原来的必填语义。

Lunar 直接生成 JSON Schema，不需要这段 Zod 兼容代码。但 `src/famou/tools.py` 的参数
此前只有类型，缺少关键语义。本轮 Feature 063 在单一 schema 源补充说明，并通过真实
AgentLoop → OpenAI-compatible → 本机 HTTP 请求抓取验证传输，覆盖 command/memory
开启与关闭的四种组合。

具体告诉模型：read_file 是有上限的头部读取，重复调用不会翻页；write_file 覆盖文件；
命令推荐 argv、没有隐式 shell 展开、使用实际单命令 timeout；记忆默认作用域和 global
共享边界。所有数字取实际实现口径，1,000,000/8,000 字节不误写为 MiB/KiB。

这是工具上下文改进，不是效果提升证据。后续实评必须另冻结新变体。

## 3. 下一优先级：预算内保留已有求解产物

来源：base 的 `opencode/skills/famou-runtime-budget/SKILL.md` 及
`references/profiling_recipe.md`、`snippets.py`、`solver_time_control.md`。

值得移植的机制是小样本计时、整个流程共用 monotonic deadline、增量原子落盘、保留已经
得到的候选，以及无 incumbent 时不能写空解冒充成功。最新文案使用 `python3 -u`、cwd
下的 tmp 和默认 10 秒余量；这些环境约定不能原样套到 Lunar。

Lunar 的命令工具用 `subprocess.run(capture_output=True)`：普通 registry 默认 30 秒，
effect subject 配置为 `min(effective_timeout, 300)`，本次 GLM 是 300 秒。`-u` 有助于
减少子进程缓冲，但模型仍要等命令结束才看到输出；没有实时流式反馈。timeout 分支也
没有保证先 SIGTERM 再留宽限，不能照搬“收到终止信号仍能落盘”的保证。

独立 SDD 应区分累计模型 tokens、整轮 wall clock、单命令 timeout，将实际剩余时间向下
传递，并约定 partial artifact 与成功候选的边界。只保留确实存在的产物及安全摘要；
checkpoint 本身不能制造 completed receipt、授权 harness 或提供分数。先做中断与原子
写入 fixture 验证，再预注册固定次数的新 GLM campaign。

现有两次 `runtime/budget_exceeded` 没有具体预算归因，不能据此断言脚本优化会修复它。

## 4. 值得后续设计：上下文压缩与按需取回

来源：`layered-compaction@5197081` 的
`opencode/tools/famou/tools/lc/{assembler.ts,runtime.ts,checkpoint/,compact/,token/}`。

优点是保留原始会话存储，用 checkpoint message ID 标识已覆盖历史，再拼接水位之后的
增量；水位丢失时保守回退。触发阈值去重、cooldown、重建后重新触发和中文 token 估算
值得参考。

不能直接移植的原因：输出被组装成三条合成 user 消息，工具仅保留名称/参数，结果依赖
`history_expand`；存在 `tool-pair.ts` 不等于原生 call/result 配对已被执行路径验证。
迁移提交说明旧测试未迁入，本次未找到这套 LC 的版本化测试。超大的最新用户消息也可能
被截断，与文档中“完整保留”表述存在差异。

Lunar 可先设计确定性的“完整工具轮次归档 + 按 ID 分页取回 + 当前请求保护”，保留原生
角色与工具配对。上下文窗口与累计 token 账本不同：压缩不能撤销历史用量；若增加摘要
模型，其调用也必须计费。不能把压缩当成本次 budget_exceeded 的确定修复。

## 5. 已有等价能力：worker 结算与恢复

来源：base 的 `tools/multiagent/lifecycle/{settle,reconcile,events,notify}.ts`。
优点是“收集事实 → 纯函数判定 → 执行状态与通知”，区分 idle/error/abort，重复事件不
重复结算，按当前会话子树惰性重建，并把结果发给直接父任务。

Lunar 已有 SQLite 权威台账、running → uncertain 恢复、条件更新、防止取消后的迟到
结果写回及相关测试。保留这些机制，后续复杂度上升时再借鉴纯函数决策拆分，不复制其
内存 registry。WebAgent 文件中提及的 integration 测试路径在当前 tree 未找到，不能
声称 settle/reconcile 的测试完备。

## 6. 保留设计原则：结果存储与跨任务记忆

结果来源：base 的 `shared/result.ts` 与 multiagent `render-result.ts`。按 UTF-8 字节
和整行保留输出尾部、稳定 message ID 命名，以及落盘失败不遮盖原结局，都值得参考。
但 `saveAt` 实际调用普通 `writeFile`，同名路径会覆盖；注释中的“永不覆盖”是依靠
调用方稳定身份的设计意图，不是 no-clobber 文件系统保证。不可直接复制为 Lunar 的
不可变证据存储，更不把任意模型/命令正文写入 Feature 061 失败 sidecar。

记忆来源：`memory_card@865a270` 的 `opencode/tools/memory-cards.ts` 和对应测试。
卡片写入保留 session provenance，检索按 user+project 作用域，避免每次新会话查不到
旧知识；结构化目标、约束、澄清、摘要、关键词与有限 top_k 值得参考。该分支不是当前
base 的祖先，master 重合入也不等于 base 已集成。

Lunar 已有 global/run 作用域、受限召回和独立 evaluator 产生的实验记忆。若未来需要同
项目跨 run 召回，可增加稳定 project scope 和来源字段；当前不需要远端向量库、服务
身份文件或额外 embedding 依赖。也不能让跨评测 run 的记忆破坏 fresh subject 边界。

## 7. 后续顺序

1. 收口 Feature 063 工具参数契约及传输测试。
2. 设计预算提示、单命令剩余时间与增量 checkpoint；同时单独评估大文件分页读取需求。
3. 为行为改动预注册新变体、固定 attempts，使用 `glm-5.1` 和已有冻结 harness；失败仍
   占分母，不覆盖 2026-09-08/09 的真实记录。
4. 有长上下文的本地证据后，再设计归档/分页取回；有跨项目使用需求后再扩展记忆作用域。

目标仍是独立、本地、能产出可验证算法结果的 Lunar Agent，并诚实测量完成率、有效性、
质量和用量。WebAgent 的实现提供设计参考，不提供当前单 case 的同条件效果保证。
