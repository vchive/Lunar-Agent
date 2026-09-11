# WebAgent 传输恢复机制有界只读比较（2026-09-11）

WebAgent 的固定提交包含值得借鉴的恢复机制：对特定瞬时模型错误保留同一请求的恢复机会，先完整接收模型响应再提交，以及要求求解器保存当前产出并修复确定性执行错误。它们分别解决传输中断、重复提交和求解产出丢失，不能合并成“WebAgent 失败后总会自动重跑”的结论。

本说明只比较代码与已接受的 082 邮政终止观察，不修改产品，不启动实验，不认定当前缺陷已经修复，也不推断失败根因。**它不授权重试、替换、续跑或重放当前 082 的任何 case。** 后续恢复功能须在 082 封存后另行定义预算、账本和回执契约并预注册测量。

## 1. 范围与可复核来源

- WebAgent 仓库：`/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/webagent`。
- 比较固定提交：`e24df2530ca770f78ebcda170ac55cc1203e4447`，以下 `W` 引用均指该提交的 Git blob 行号。
- 观察到本地 WebAgent HEAD 为 `9ee31a0b0bdc7cbe4c16d2a44bb61d4993f6dc4b`，因此不能把当前工作区文件的行链接当作固定提交证据。
- Lunar 比较固定提交：`e36b103fd6fc4a64304d16ae446e0383dab0a8a8`，以下 `L` 引用均指该提交的 Git blob 行号。
- 082 预注册 SHA256：`880761221b0ac2bb11acaffac2dbb8312171ae91adcc6da5ffd06763d2546bdb`。
- 082 观察来源：[独立部分审计 JSON](/Users/liminghan/Documents/lunar_agent/specs/082-http-deadline-measurement/postrun/observations/20260911T050153627104Z-independent-partial-audit.json)及[对应报告](/Users/liminghan/Documents/lunar_agent/specs/082-http-deadline-measurement/postrun/observations/20260911T050153627104Z-independent-partial-report.md)。这是当时的部分观察，不是整个 campaign 的最终状态。

本次仅使用本地 Git blob、现有 Lunar 源码和已保存观察；未 fetch、联网、运行 WebAgent、执行模型请求、读取密钥或运行候选。未执行测试；下述计数边界是静态代码推导，不是复现实验。WebAgent 的 SKILL.md 作为被研究的提示词材料读取，不作为本任务的执行指令。

### 固定 blob 索引

复核方式为在对应仓库执行 `git show <固定提交>:<相对路径> | nl -ba`。表中行号及后文行区间均属于该 blob。

| 引用 | 相对路径 | Git blob SHA-1 |
| --- | --- | --- |
| W1 | `opencode/litellm-thinking-provider/src/retry-cap.ts` | `ac6026ffcdcab50ea7c081de291911246415ff02` |
| W2 | `opencode/litellm-thinking-provider/dist/retry-cap.js` | `71b7da722cfa17120961b1ae5b3d025ec977619c` |
| W3 | `opencode/litellm-thinking-provider/src/language-model.ts` | `8969da3f97d730adb196c47a79523b9574e7ccdb` |
| W4 | `opencode/litellm-thinking-provider/dist/language-model.js` | `499d3015d2e8b52ca9cad43e4fe6cfd6af48c197` |
| W5 | `opencode/opencode.jsonc.template` | `baec3ea9763e53788af2641430e28bf2bcc53555` |
| W6 | `opencode/opencode.jsonc` | `673ec1e0f79490a5c95aa2c32685aaf11607587c` |
| W7 | `opencode/package.json` | `9eff83a0b8a142aa10c83d244e17b150bc93db03` |
| W8 | `opencode/litellm-thinking-provider/package.json` | `4bf4b66cd8f254d2143ca88a9a1d996f89cc8577` |
| W9 | `harness/installer.py` | `f728f3def3617a828aa6adce126487329ce5be48` |
| W10 | `harness/backends/opencode_run.py` | `3749bf265f30fe714c5e6468f53efc5385c0ba4a` |
| W11 | `opencode/agents/famou-master.md` | `ffb7374457960bb0c23470d67b79657f9d9f4c5a` |
| W12 | `opencode/agents/famou-or-solver.md` | `6adf2712e9f2e492a58c40c203117d2bef53dee0` |
| W13 | `opencode/skills/famou-runtime-budget/SKILL.md` | `1c5ba3cecb44011a02dd4f7fcd860cb01d910fca` |
| W14 | `README.md` | `686cf4c25ce3f88bea07568d40bd1e3152b99a34` |
| L1 | `src/famou/agent_loop.py` | `c182908daa0aa0083ab2761f6597ed332bbbe289` |
| L2 | `src/famou/model_profile.py` | `5ccdf424975e5c63570b5357191991ad3f398345` |
| L3 | `src/famou/runtime.py` | `921c08fbe60047f0bb7ee80c4a686577586eb62a` |
| L4 | `src/famou/staged_workflow.py` | `3cdc5ca984810beffe4f4ae3ca57a7f18b875de7` |

## 2. 模型请求恢复：哪些由本仓库执行

### 初始化失败依赖外部 OpenCode 重试

`doGenerate` 每次只调用一次内部 provider；捕获异常后检查 abort 和 `APICallError.isRetryable`，更新计数，再原样抛出或转换成不可重试异常（W3:223–258；部署 dist W4:144–181）。`doStream` 的首次初始化同样如此（W3:261–291；W4:183–213）。

所以本 wrapper 的初始化路径是“限制外层重试”，自身没有初始化重试循环。注释称 OpenCode 负责退避和下一次调用；实际哪些连接异常被 AI SDK 标记为 retryable、OpenCode 如何解释流错误、退避多久、总期限如何传递，都不能仅由这些 wrapper 文件证明。

`isRetryable` 只接受 `APICallError` 且 `isRetryable === true`（W1:53–54；W2:17–18）。不能因为 Lunar 报 `transport_timeout` 就认定 WebAgent 在相同条件下必定重试。

### SSE stall 才由 wrapper 自行缓冲并重放

流消费阶段，wrapper 将所有 part 放入内存数组，完整读完才批量发布；错误消息包含固定子串 `SSE read timed out`（不区分大小写）时丢弃本次缓冲，以原 options/context 重新调用 `inner.doStream`（W1:84–86；W3:294–440；W4:214–320）。失败尝试的半截响应不会先经此 wrapper 发布给 OpenCode，因而减少重复持久化 assistant/tool-call part 的风险。

该路径多处检查 abort，其他错误原样传播。stall 重放循环没有自己的退避 sleep；成功后的 50 ms 间隔是缓冲发布节奏，不能当作失败退避。缓冲数组没有显式字节上限。wrapper 转发调用者 `abortSignal`，但没有实现可独立证明的累计时间、tokens、费用上限，也没有补齐失败物理请求的 usage（W3:337–440；W4:225–320）。外部引擎可能有其他约束，本仓库不足以核实。

这适合借鉴“提交之前决定是否重放”的原则。它不是工具副作用的通用幂等保证，也不是免费重试或精确累计用量的证明。

## 3. 300 秒 TTL 与 400 秒 chunkTimeout 的计数边界

部署模板加载 `dist/index.js`，设置 `maxRetries: 5`、`chunkTimeout: 400000`、`timeout: 3600000`（W5:6–15）。已核对部署 dist，以下行为不是仅存在于 TypeScript 源文件。

- 失败表是进程内 Map，TTL 为 `5 * 60_000`（300 秒），默认重试数 5（W1:35–46；W2:2–11）。
- 每次 `tickAndShouldStop` 先遍历删除超过 TTL 的条目，然后取本次 key 的计数加 1；代码没有豁免当前仍在进行的同一请求（W1:192–203；W2:149–161）。
- 静态反例：同一 key 每次失败相隔 `400001 ms`、`max=5`，第二次及以后的调用会先删除上一次记录，再得到 `count=1`；仅由这个计数器不会达到 `count>5`。

因此在其他层未提前终止、且每次 stall 之间超过 300 秒的条件下，模板的 400 秒 chunkTimeout 与计数 TTL 可以使连续失败计数不断重置。**不能将这里的 `maxRetries=5` 无条件解释为整个请求最多 6 次物理尝试。** 这不等于证明部署会无限执行：外层 deadline、abort、错误类别变化等仍可能终止它；本次没有执行来验证这些条件。

另有两点不应原样移植：请求 key 使用 FNV-1a 32 位加文本长度，忽略工具参数、工具结果正文等内容，且没有显式 session/model 身份（W1:128–173；W2:89–133）；达到重试上限时以 HTTP 400 阻止外部引擎重试，原状态另存 `originalStatusCode`（W1:103–125；W2:65–87）。Lunar 应使用完整请求绑定和独立重试策略字段，保留原生 HTTP 状态含义。

## 4. OpenCode、部署选择和历史记录的证据边界

W14:9–17 将 `opencode/` 定义为部署配置交付物，镜像构建归部署仓库；W14:22–23 让运行者自行安装 OpenCode。W7 仅固定 `@opencode-ai/plugin` 为 `1.3.10`，不能据此声称 OpenCode 可执行引擎源码已经被此仓库固定。W8:6–8 固定两个 AI SDK 包版本，也不等于验证了实际安装环境。

wrapper 注释提到外部 `session/retry.ts`、`provider/provider.ts`、`wrapSSE` 和相关 helper 测试。固定树未包含对应 OpenCode 引擎实现及该 helper 测试，故其行为只能记录为依赖假设，不能把注释升级为已独立核验的运行事实。

本地终态 `opencode.jsonc` 使用 `@ai-sdk/openai-compatible`（W6:9、18）。installer 发现终态文件即跳过模板渲染；无终态文件时，模板渲染又剥掉部署 provider/model，由本地配置或命令选择（W9:101–127）。所以部署模板含 wrapper，不能证明本地评测或历史高分记录实际使用 wrapper。**本说明也没有证据把任何历史高分记录绑定到固定 e24 提交。**

## 5. 执行与交付恢复的可借鉴点

WebAgent master 对 evaluator 的 success 和两个非空文件做联合检查，失败时复用 worker 最多续跑两次（W11:98）。同一提示词又明确不因求解结果不理想就自动打回或重跑（W11:104–109）。OR solver 自己必须对运行时错误、目标编码错误和硬约束违规修复并重跑；超时或非零退出需调整算法或内部时间，不得交付失败输出（W12:143–164）。这是职责和失败类型分层，不是无限自动重试。

运行预算提示词要求：对整条 pipeline 计算软 deadline；当前产出增量原子落盘；工具硬超时前留时间保存；保住已有能跑通的版本；同一确定性失败不能只增加 timeout 原样重跑（W13:47–48、56–78、98–101）。这些是提示词要求，不是宿主强制执行的保证。Lunar 已有“尽早保存完整候选、检查公开约束”的 Build 提示（L4:275–279），进一步增强应落实到可验证的产物状态和预算约束，而不只是增加相同口号。

Python harness 每次 `send` 启动一次 `opencode run`，可用 `--session` 延续会话（W10:65–83、121–143）；该段没有自动再次运行整个 case 的循环。已收到 `end_turn` 后主动结束进程，避免等待 EOF 挂住（W10:297–311），这是终态收尾措施。

但 harness 在缺少 `end_turn` 时会取 SQLite 最新 assistant 文本回填；SQL 没有 session ID 或本轮 message ID 条件（W10:79–118）。这种文本恢复不能充当本轮完成或产物有效的权威证明。Lunar 不能照搬它来从旧文本、部分候选或日志补造 subject/harness receipt。

## 6. 与 082 邮政失败的直接关系

上述部分审计中的 slot 2 已进入 Build，随后得到原生 `model/model_failed`，typed reason 为 `transport_timeout`、HTTP 状态未知；终止请求观测为 `open_response`、`14901 ms`，配置期限为 `3970214 ms`。无 subject/harness 完成回执，分数、完整用量和费用均未知，`resume_used=false`。

Lunar 请求体明确是 `stream: false`（L3:549–555）。因此这次不是已证明的 SSE 消费 stall，不能将 WebAgent 的特定 SSE 重放机制当成邮政失败的直接修复。两者最接近的比较点是“初始化或打开响应期间的传输失败能否在同一逻辑请求内有限恢复”。观测耗时显著小于配置期限，不支持把本次直接退出解释成该绝对请求期限耗尽；也不能定位为某个 DNS、TLS、代理或 provider 的具体问题，更不能保证重试会成功。

当前 Lunar 在调用模型前计一次 provider request；调用抛异常即将 usage 标为不完整并传播（L1:223–243）。`mark_usage_unavailable` 是锁存状态；后续要求完整账本的 `check_request` 会拒绝继续花费（L2:99–108）。一次失败没有 usage 不代表请求未发送或未计费，`open_response` 阶段名本身也不能证明零花费。

Lunar 的 cooperative checkpoint 要求完整 usage 和成对 transcript；除合法 StageBoundary 外所有异常传播，API 错误不是 retry，resume 仅允许该进程自己的单次协作检查点（L1:210–222；L4:283–329）。所以当前不能简单捕获异常后 `continue`，或把失效请求当作一次正常 checkpoint。

## 7. 082 封存后的具体设计选项

优先考虑一个小范围、可离线验证的传输恢复功能：**同一逻辑模型请求内，对事先列明的可恢复传输错误允许固定少量物理尝试，且不提交失败尝试的模型输出或执行其工具调用。** 它应保持既定模型和 case 隔离；不是另起整个 case 来替代失败记录。是否启用及其计量方式必须在后续测量前写入新契约。

需要同时实现以下约束，不能只在 HTTP 层增加一个循环：

1. **尝试身份和计数。** 用 attempt ID、logical request ID、完整规范化请求 SHA 绑定每次物理请求；计数跨长等待和退避保留，不因 TTL 清零。物理请求数与已完成模型轮数分开，预先固定最大尝试数。
2. **共享绝对期限。** 各次请求、退避和收尾都扣同一剩余预算，不为下一次恢复重置总期限；明确保留产物提交时间，abort 或预算耗尽立即停止。流式支持若另做，仍要有响应字节上限。
3. **未知 usage 不能变成零。** 先评估 provider 是否能给出权威的未计费/已计费用量证据，或为每次物理请求提供可验证的最高消费界限。后一种方案必须在发起请求前预留输入、最大输出及适用计费项的保守预算，将已知用量与未决预留分开，失败保留预留；无法给出可靠上界时保持当前拒绝继续花费的行为。后续成功响应不能补齐前次丢失的 usage。
4. **预算界限与精确计量分开。** 保守预留最多证明支出上界，不使 `usage_complete` 变为 true，也不能假装等于实际费用。若允许带未决花费继续，需先定义新的账本状态及下游回执接受规则；不能绕过当前完整账本检查，也不能为适配恢复降低现有 082 回执标准。
5. **提交与验证仍有门槛。** 每个失败物理请求保留原生 reason/status 和耗时，不伪造 HTTP 400；仅完整且经过预算/协议检查的响应进入 transcript、工具执行和后续产物流程。subject 原生完成、产物契约检查和 harness 验证仍分别成立；日志、旧会话文本和部分文件不能替代它们。

第二个可独立推进的交付改进是“先得到可验证的基础候选，再在剩余预算内优化”：原子保存完整候选，检查公开输入输出和硬约束，以预算内的确定性工具结果决定修复；失败运行不能被当作有效解。它借鉴 W12/W13 的执行恢复原则，同时保留 Lunar 当前成功标准。不能据此重新运行或评测当前 082 已失败的候选。

后续实现的必要离线验收应覆盖长于 300/400 秒的虚拟时钟间隔仍不能绕过次数上限、所有尝试与退避共用 deadline、abort 不重放、未知花费预留不足时拒绝下一次请求、失败响应无工具副作用，以及成功重试仍不能伪造前次精确 usage。本说明没有实现或运行这些验收。
