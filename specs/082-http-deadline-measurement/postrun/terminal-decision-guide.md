# Feature 082：终局判读与后续开发依据

2026-09-11，运行期间的只读代码审查。本文不是实验结果，不关闭 T082-05/06。
最新独立阶段观测见 `observations/20260911T044152076409Z-independent-partial-audit.json`：
两槽均已验收计划并进入 Build，终止及 subject/harness 回执均为 0，结果仍未决。

## 当前目标

让 GLM-5.2 在钣金套料、邮政揽收两个既有高分 case 上完成分阶段交付，并得到原生
EffectTrialRunner/exact harness 的有效性与分数。Feature 069 的普通流程已有两例有效结果
（0.999999、1.0185），继续作为已有交付依据；082 单独检验当前分阶段流程，历史结果不
进入本轮分母。完成规划交接尚不能证明交付改善。

## 冻结代码实际采用的时间边界

源码固定 `e36b103fd6fc4a64304d16ae446e0383dab0a8a8`。`staged_workflow.py` 的 `_remaining()`
从 5400 秒中扣除自 staged.run 开始的累计耗时及 120 秒预留；Master 使用它与 1200 秒
的较小值，首次 Build 和续跑都使用剩余共享时间。`agent_loop.py` 在每次模型调用前再
减去当前 loop 已用时间，将余量传给 `model.complete()`。2400 秒不单独限制 HTTP 请求。

首次 Build 在完整工具批次结束、下一次请求前检查 2400 秒或第 32 个轮次边界；32 不是
32 次独立工具调用。共享时间与账本检查优先，耗尽时不能借 checkpoint 重置。仅完整
usage、工具配对 transcript 及合法 checkpoint 授权同进程续跑一次，续跑保留累计账本。
API 错误、超时和未知用量不会触发该续跑。因此，长请求跨过 2400 秒本身不说明 checkpoint
实现出错，也不能由它推断延长预算必然有效。

## 等原生终止证据后的决策

| 终局证据 | 本轮应记录 | 后续开发依据 |
| --- | --- | --- |
| 原生 subject 与 harness 回执均获验收 | 原始 validity/overall/quality；保留大于 1 的分数 | 检查交付是否成立，按 case 描述；单次结果不足以证明稳定性或超越历史平台 |
| 原生 subject 失败，合法 v4 传输超时 | 固定 reason、phase、可空 HTTP status、请求 elapsed/timeout | 若最后请求等待接近上限，可研究请求预算策略；不直接归因 provider 或算法 |
| 响应契约校验失败 | 原生固定 invalid_json / invalid_tool_calls / invalid_usage 等原因 | 优先定位实际响应契约兼容问题，不能当作求解质量零分 |
| subject 已验收但 harness 失败或结果无效 | 保留原生阶段和实际回执/评分状态 | 按实际 harness 证据定位交付或求解问题，不执行候选补分 |
| 诊断缺失、拒绝或外层终止 | 缺失字段保持 null，区分进程结束与 workflow 最后阶段 | 只陈述可证实的失败边界，不补写未知原因 |

v4 `elapsed_ms` 是最后失败请求的累计观察窗口，涵盖 helper、IPC、HTTP、清理及验证等
已计时步骤，不是最后 `phase` 独有耗时，也不是 Master 精确耗时。`open_response` 不能
区分 DNS/TLS/代理/排队/生成/helper 启动；`transport_error` 也可能来自 helper/IPC/OS。
HTTP 错误正文处理达到 deadline 时仍可能保留 `http_error`，不能据此断言未超时。
完整失败用量、费用与历史 078 的细分原因均不能从这些字段恢复。

## 终局收尾顺序

1. 等两槽及 dispatcher 原生终止记录，收集 watcher 正常退出证据。
2. 独立运行当前 082 `postrun/audit.py --require-complete`，保存最终 JSON 及原样报告；
   root 核对 native summary、实际证据 SHA、固定分母与诊断投影。
3. 以启动身份、subject/HTTP 进程组、后续 harness 身份、可见后代及 scoped argv/cwd
   关联检查残留；注意 extractor/evaluator 的独立进程组和私有 case cwd。进程检查是
   单独的时点观察，不能由 SHA 审计或 watcher 简化列表替代。
4. 只检查候选文件元数据，记录交付路径存在性；不执行或补评失败候选。确认冻结源码、
   helper、输入及 074/076/078 历史封存字节不变，不运行旧 live-source 审计。
5. 达到 final acceptance 并完成进程核验后关闭 T082-05/06，更新结果与 HANDOFF，
   提交推送封存。任何产品修复需独立 SDD，封存前只可在隔离 worktree 开发，不能混入本轮。

本指南没有执行模型、WebAgent、平台查询、provider 探测、候选、重试或新 campaign，
没有修改正在测量的代码、参数或证据。是否需要下一项产品改动，由本轮终局证据决定。
