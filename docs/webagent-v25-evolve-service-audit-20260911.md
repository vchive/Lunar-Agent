# WebAgent v25 `famou-v2` 进化服务审计

日期：2026-09-11
审计对象：WebAgent 固定提交 `f6ad20caf8963d105fe26c96b6a30ef4dfd34859`
对照提交：`e24df2530ca770f78ebcda170ac55cc1203e4447`
范围：只读 Git blob 分析；未读取部署 URL/密钥文件，未访问服务、未执行 CLI/评测器、未提交产品改动。

## 结论

`famou-v2` 在这条集成链里是服务路由名称，不是 Lunar/OpenCode 本地可等待的 agent。`famou-client.ts` 读取 `/root/.config/opencode/tool-url/famou-v2`，再以 `famou-ctl ... --api-url <url> --api-key <key>` 调用外部服务；进化状态在服务端，插件进程不保存 worker 名册。`evolve_create` 返回实验 ID 后由 `evolve_status/list` 查询，不能用 `agent_wait` 等待（fixed `lib/famou-client.ts` blob `bc0d81938a319fbc42400830887c307517b1d931`，行 61–79；fixed `evolve/index.ts` blob `0897a131dfa00d74eba8bd67a7514574e38b0e4d`，行 16–28、65–66）。这不等于服务端内部没有 agent，只说明本地适配层是远程服务控制面。

这套外部服务模式在旧 e24 已存在。两提交的 evolve 文件中，client、family index、status/list/continue/update/cancel/sync 均 byte-identical；唯一改动是 `evolve_create.ts`（fixed blob `46167cc611f9109da25f482d618e5b24db1b08c1`，旧 blob `2feb230f914959d5fac08da27de2d8b18327fc4f`）。因此不能把“引入 famou-v2 服务”归因于当前 v25 更新；当前新增主要是创建参数摘要和一段暂时关闭的预检。

对 Lunar 的可迁移价值是边界和账本设计：把远程后端作为显式可选控制面；提交不可变的材料清单和预算；用服务端实验 ID 做状态/reconcile；把评分函数和回执绑定在同一版本的评测包中；遇到超时或未知结果时先查询，禁止盲目重建。不能直接把 WebAgent 的远程 CLI、其提示约束或服务端结果当作 Lunar 原生 `EffectTrialRunner`/FM-Eval 评分权威。Lunar 当前目标仍是 GLM-5.2 分阶段 Master→Build，经原生 harness 交付并获得有效解；本审计不授权新评测、provider 探测或重开旧槽。

## 固定源码证据

| 组件 | fixed blob | 关键行为（fixed 行） | e24 对照 |
|---|---|---|---|
| `evolve/lib/famou-client.ts` | `bc0d81938a319fbc42400830887c307517b1d931` | URL 文件、CLI 参数、子进程、超时/abort、JSON envelope（61–107） | 相同 blob |
| `evolve/index.ts` | `0897a131dfa00d74eba8bd67a7514574e38b0e4d` | 七工具注册；服务端状态；无 `workerID`（42–51、65–82） | 相同 blob |
| `evolve_create.ts` | `46167cc611f9109da25f482d618e5b24db1b08c1` | 创建输入、180 秒调用、ID 提取、失败状态（22、103–191） | `2feb230f914959d5fac08da27de2d8b18327fc4f`，本文件唯一 evolve 差异 |
| `evolve_status.ts` | `95d3cbed4f8606d8e9acd8b778e8ec6244ba6e78` | 60 秒查询，返回不透明数据 | 相同 blob |
| `evolve_list.ts` | `c8fd8374436b06b2474c4e2d2abd4f32e470624c` | 60 秒列举/状态过滤 | 相同 blob |
| `evolve_continue.ts` | `d4edfdd4442a1f1b7d847a8d4dd8b6b1bbd9d54a` | 180 秒；迭代 10–200，默认 50 | 相同 blob |
| `evolve_update.ts` | `c8b0a023d3d05de62ab288ff84dd86a819589704` | 180 秒；传配置和实验 ID | 相同 blob |
| `evolve_cancel.ts` | `9499fd69b29e11f9b867f0e83e7d666bdf63f565` | 初次 `confirm=false` 不接触服务；二次确认后取消 | 相同 blob |
| `evolve_sync.ts` | `de5c1f5ef8f7fef5d440f561fd3633ad9ed155b6` | 180 秒；同步到当前目录直接子目录 | 相同 blob |
| `famou-evolve-experiment-submit/SKILL.md` | `e4378a06e708d278583841344eb394fcf7349799` | 材料、配置、评测器检查清单 | e24 为 `3b777aeb9c7095a2f7f2daebea60b166bef47a97` |
| `config_ref.md` | `db2950e021e09217ea9adac2705c7e8401f4c946` | 配置示例和相对路径 | e24 未有该路径 |
| `prompt_ref.md` | `80c9c0aa6cb6e7773dc4e020fcb7a8dbdc20debf` | prompt 约束和长度指引 | e24 未有该路径 |
| `famou-evaluator-guideline/SKILL.md` | `26e49a3c303a747b3b6da3c0898c315db7b0ca94` | `evaluate()`/`--mode eval` 契约、评分原则 | e24 为 `1ca7df596a681d92ac2d69cfc320b92aa7d4a777` |
| `famou-evaluate.md` | `337d7aa9e7f782e2abc5a02c3938118d131b3066` | 评测器独立性和约束测试建议 | 相同 blob |
| `non-prediction-task.md` | `35227786fef841ed563df3f4bfedb3c2a5446c27` | 单程序入口、一次运行、超时/格式错误语义 | e24 为 `32fbbae366e050e4c7094b565450f5c5b7d64ade` |
| `prediction-task.md` | `dc00101befc508587f16ecce25df3bc3f9b3f794` | train/predict 两阶段和独立评分 | e24 为 `60c6060163e2a155414ff9f3cc6164556196ffaa` |
| `famou/index.ts` | `aea0b1e6394bd72c73d15fa7e5d676c5693aedf3` | approval executor/hook 接线 | 相同 blob |
| `approval/tool-executor.ts` | `69a1359590a559ed0c7154b59e33ec928867d345` | 受控工具执行、适配器、abort | — |
| `approval/block-famou-cli.ts` | `de99b588f03b54079b8d02f58e7e65c7b61da7bd` | CLI 启发式阻断（明确不是安全边界） | — |
| `approval/limits.ts` | `475f9a1f7bac431f772dceadd177c95e2b9f45b8` | 受控工具等待上限 3 分钟 | — |
| `approval/gate.ts` | `1518ef3d83719b241d0dca0447f96f4378c3aaaa` | 会话串行、timeout/abandon 结局 | — |

## 提交材料、预算与 ID

提交 skill 要求在 `submit/`（或明确替代目录）准备 `init.py`、`evaluator.py`、数据、`prompt.md` 和 `config.yaml`，检查配置引用的本地文件，并以 `job_YYYYMMDD_HHMMSS` 命名；后续操作在该目录完成（`SKILL.md` 行 14–28）。评测器必须暴露

```python
def evaluate(path_user_py: str, timeout: int = 3600) -> dict:
    return {
        "validity": float,
        "combined_score": float,
        "error_info": str | list,
        "detailed_scores": dict,  # optional
        "is_maximize": dict,      # optional
    }
```

并同时允许 `evaluate(path_user_py)` 和核心三字段（行 36–49）。导入检查使用 `exec_module`、可调用性和 `inspect.signature(...).bind("dummy_init.py")`（行 63–86），但导入会执行模块顶层代码，因此不是纯静态安全证明；它也没有运行评测器函数体。配置/评测器检查不能推断当前工作目录或脚本目录的数据（行 53–55）。

配置示例规定相对路径相对于配置文件目录，并包含 `evolve_config.max_iterations`、`initial_program`、`evaluator`、`system_message`（`config_ref.md` 行 1–9）。新创建工具的 schema 还要求 `property.max_iterations` 为正整数、`property.gpu` 为布尔值并复制配置摘要（`evolve_create.ts` 行 103–122）。不过示例遗漏顶层 `gpu`，这是模板不完整性；不应写成已验证的运行时失败。

创建调用只把 `config_path` 和 `evolution_name` 传给外部 `famou-ctl`（`evolve_create.ts` 行 124–135），`property` 没有转成预算参数；配置正文和服务器端预算由外部 CLI/服务解释。配置一致性校验函数虽存在（行 198 起），执行调用仍被注释（行 124–126），所以当前运行不强制摘要和 YAML 一致。`max_iterations` 只做正整数检查，没有上限；继续操作才有 10–200、默认 50 的本地范围（`evolve_continue.ts` 行 9–26）。因此 Lunar 借鉴时应把总迭代、GPU/时间、重试次数和共享期限放进不可变预算账本，而不能只信 UI 摘要。

创建成功的判定是子进程退出码 0 且 envelope `success=true`；随后从 `data.experiment.exp_id` 尝试提取 ID（`evolve_create.ts` 行 136–147）。ID 缺失时仍可能返回 `ok:true/state:changed/experiment_id:null`，这是弱接受条件。失败、超时、环境不可用均返回 `ok:false/state:unknown`，创建没有自动重试（行 149–191）。未知创建结果不能安全地再次 create：应先 `list`/`status` 按实验名或服务端 ID 线索对账；该 wrapper 没有幂等键或 exactly-once 保证。

## 恢复和文件边界

- `status` 是单实验只读查询，`list` 是发现 ID/可选状态过滤；返回数据保持不透明，未在本地验证日志、checkpoint、leaderboard 或 score receipt。
- `continue` 针对已有 population 追加迭代，`update` 声明运行中只允许 prompt 更新和 `max_iterations` 增长，但 wrapper 只传 ID/config，不做本地 diff 验证。
- `cancel` 的 `confirm=false` 明确不联系服务并返回 `executed=false/state=unchanged`；二次 `confirm=true` 后调用远端。确认是无状态布尔参数和用户消息规则，不是签名 challenge、session nonce 或防重放令牌。失败返回 `executed=true/state=unknown`，应重新 `status`。
- `sync` 目标固定为 `./<experiment_id>`；先做词法 `resolve` 和直接子目录检查，然后把同步交给 CLI。没有 realpath/symlink 保护、内容/hash/score 校验、watch 或自定义目标；非空目录由服务端返回 `CONFIRMATION_REQUIRED`（`evolve_sync.ts` 行 10–68）。
- client 的本地 timer 在读取 URL 文件并 spawn 后才开始；kill 子进程只表示本地 CLI 停止等待，不证明远端任务取消或停止计费。stdout/stderr 用完整 `.text()` 读取，没有字节上限；envelope 只校验 `success` 布尔和 `msg` 字符串，`data` 不做结构验证（`famou-client.ts` 行 37–55、82–107）。argv 返回值只遮住 `--api-key` 后的一个参数，原始 stdout/stderr 和进程级环境不做全面脱敏。

## 评测器与分数权威

指南把 `evaluate(path_user_py, timeout=3600)` 定义为 famou-v2 接口，把 `--mode eval` 定义为对既有产物的 master 评分；两入口应共享一个 score 函数（`famou-evaluator-guideline/SKILL.md` 行 6–7）。评测器以独立原始数据运行被评估程序，数据锚定在 evaluator 自身位置，产物写临时目录；格式/运行错误抛异常，硬约束违反返回 `validity=0`、`combined_score=0`，合法结果为 `validity=1`，combined score 非负且越大越好（`famou-evaluate.md` 行 66–84、203–208）。

非预测模板以 `python3 solve.py --input_path <IN> --output_path <OUT>` 为程序接口；`score(out_path)` 评分既有输出，`evaluate()` 在临时目录运行一次并评分，子进程失败/超时抛错（`non-prediction-task.md` 行 10–12、22–24、64、109–139）。预测模板要求 train/predict 分离，evaluate 重新训练后预测，再调用同一 score；示例的 train/test timeout 由两个变量传入（`prediction-task.md` 行 119–155）。这些是提交方的评测器契约和方法建议，不是 evolve wrapper 对远端 payload、数据 hash、评测器版本或 score receipt 的本地验证。

因此服务响应中的 `data`、leaderboard 分数或成功消息都不应直接成为 Lunar 评分权威。Lunar 应继续以固定 native harness、固定输入快照、固定 evaluator 版本和可验证 receipt 作为唯一成绩来源；远端进化只能生成候选和实验状态。

## Approval 与安全边界

当前 family 注册七个工具；注释说明只有 `evolve_create` 默认走 approval，因为它创建不可撤销且立即可能产生费用（`evolve/index.ts` 行 14–22）。`readEvolveOutcome` 只把明确 `ok:false` 转成 approval failure；JSON 解析失败、非对象或缺少 `ok` 会返回空对象，属于 fail-open（行 68–82）。

approval gate 在同一会话串行化有副作用的动作，并给执行器注入 AbortSignal；到 3 分钟时 abort 并停止等待，但工具若忽略 signal 仍可能在后台运行（`limits.ts` 行 46–54；`gate.ts` 行 151–229）。因此它不是远端停止证明，也不是共享预算。`block-famou-cli.ts` 自己明说 shell 拼写、变量等可绕过，属于启发式 UX 防护而非安全边界。对于 Lunar，安全边界必须落在执行环境、参数白名单、服务端鉴权和可验收回执，而不是模型提示或字符串正则。

## 对 Lunar 的最小迁移建议

1. 保留本地/native 路径为默认且唯一评分权威；把远程服务做成显式 backend，失败或不可用时不得静默改变评分语义。
2. 在提交前生成不可变 bundle manifest：初始程序、评测器、prompt、数据引用、配置、版本和 SHA-256；把 GPU、最大迭代、总墙钟、物理尝试数、重试上限和共享截止写入同一预算记录。
3. 每个远程/本地试验使用唯一 experiment/trial ID；创建响应必须含非空 ID、bundle hash、预算回显和服务端 receipt 才能进入 `changed`。超时、断连、缺 ID 一律 `unknown`，先按 ID/幂等键查询再决定恢复，禁止盲目重建。
4. 把 `evaluate()` 与既有产物评分绑定到同一 evaluator 版本和输入快照，保存 validity、combined_score、详细指标、约束结果及 receipt hash；没有完整回执时不得把服务消息当分数。
5. 把 continue/update/cancel/sync 视为状态改变或文件写入操作，分别记录前后状态和预算扣减；取消确认使用一次性 token/用户确认关联，而非可重放布尔值。
6. 明确“本地等待结束”“远端任务停止”“费用停止”是三个不同事实；本地 abort 只能结束等待，除非服务端返回可验证取消/计费终止回执。
7. 先用已有 WebAgent 高分 case 的静态数据设计适配器和回执校验，再登记新的 Lunar 真实评测；不重跑 WebAgent、不把其成功率外推为 Lunar 有效解率。
