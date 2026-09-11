# Feature 082：HTTP 截止版本真实测量终局

2026-09-11 14:21:02 +0800，两条登记的新 S 尝试全部结束。两例均验收 Master 计划并
进入 Build，均在模型调用阶段失败，未生成 subject 完成回执、未启动原生 exact harness。
本轮分阶段有效解 **0/2**；所有 validity、overall、quality、完整失败 usage 和费用均为
`null`。未知分数不能当作质量零分，文件存在也不能替代原生评分。

| 观测 | 钣金套料（slot 1） | 邮政揽收（slot 2） |
| --- | ---: | ---: |
| 计划验收 / 进入 Build | 是 / 是 | 是 / 是 |
| Subject 原生耗时（秒） | 5280.137 | 1324.816 |
| Subject 退出码 | 2 | 2 |
| v4 stage / code | model / timeout | model / model_failed |
| typed reason | transport_timeout | transport_timeout |
| 最后请求 phase | open_response | open_response |
| 最后请求耗时（秒） | 4036.528 | 14.901 |
| 最后请求允许时间（秒） | 4036.519 | 3970.214 |
| HTTP / response_status | null / null | null / null |
| 已观测模型响应 / 工具结果计数 | 16 / 24 | 14 / 17 |
| checkpoint / 续跑 | 无 / 否 | 无 / 否 |
| Subject 回执 / harness 回执 | 无 / 无 | 无 / 无 |
| validity / overall / quality | null / null / null | null / null / null |
| 完整失败 usage / cost | null / null | null / null |

表中 subject 耗时取原生 `subject-terminated.json`。原生 run 汇总另记录 5280247 和
1324926 ms，包含不同的记录边界；不得混称为精确 Master 或 Build 耗时。模型/工具计数
跨阶段累计，也不是完整用量。两槽 workflow 最后仍保存 `build_running`，它是最后阶段，
不代表进程还活着。

## 这次具体卡在哪里

钣金最后一个模型请求消耗了约 4036.5 秒的运行时预算，观测耗时比传入期限多 9 ms，
在尚未观察到响应头的 `open_response` 阶段终止。这与本次本地期限附近结束的行为一致，
不能由这一个样本宣称所有调用都具有相同返回精度，或证明交付已经改善。

邮政最后一个请求在 14.901 秒时已报告传输超时，远小于允许的 3970.214 秒。本次直接
失败条件不是共享预算耗尽。现有兼容映射允许 typed `transport_timeout` 与 legacy
`model_failed` 同时出现，不能把这种组合误当成诊断不一致。

两例都不能进一步定位为 DNS、TLS、代理、连接或特定 provider 原因。`phase` 是最后观察
位置，`elapsed_ms` 是最后失败请求的累计计时窗口，包含 helper、IPC、HTTP、清理等已
计时步骤，不是该 phase 单独耗时。完整失败用量、费用和服务端是否继续计费仍未知。

Build 的 2400 秒阈值只在完整工具轮次后的安全边界检查。长模型请求可能使用共享余量；
超时不会变成合法 checkpoint。邮政在 2400 秒和 32 轮边界之前失败；钣金最后一个长请求
结束时共享工作时间已经耗尽。因此本轮没有续跑，不能据此评价续跑收益。

## 交付文件元数据

Root 在最终审计后只检查了路径、文件类型和大小，并确认两次元数据读取一致，没有
读取或执行候选内容、补跑评分或复制旧候选。详见
[最终候选元数据](final-candidate-metadata.json)。

- 钣金：计划声明的 `solve.py`、三份 output 文件和 `_agent_summary.md` 均不存在，
  也没有 `receipt.json`。
- 邮政：`solve.py` 为 25027 字节；`output/solution.json`、`assignment.csv`、
  `stations.csv` 分别为 44259、9464、475 字节。摘要及完成回执缺失；这些文件没有经过
  本次原生 harness 验证，不能认定为有效解。

## 主机休眠与时间解释

原生 campaign 墙钟起止为 12:28:28.039776 至 14:21:02.244734 +0800，差值 6754.205 秒。
当前 Python 的 `time.monotonic()` / `perf_counter()` 绑定 `mach_absolute_time()`，不
累计系统睡眠；staged、HTTP 与外层 `subprocess.wait` 均使用该语义。因此原生耗时与
墙钟时间不同，不能把二者差值直接当作某层 deadline 超限。

本轮已保存的只读功耗投影含 Sleep 33、Wake 35、DarkWake 32 条时间戳/枚举，足以说明
不能假设主机全程保持唤醒，但不能据此精确重建睡眠总秒数或解释任一传输失败的具体原因。
此前 13:56 墙钟 ETA 已撤回。没有改变本轮主机电源配置、计时器或冻结条件。详见
[时钟语义与证据](clock-semantics-review.md)。

## 独立核验与封存

被测源码固定 `e36b103fd6fc4a64304d16ae446e0383dab0a8a8`，GLM-5.2；登记提交
`021b3d0396d3dbe982dd250b5da956bbc7ce469f` 在唯一启动之前已推送。各 case 一个新 S 槽，
一波并发 2，Master1200 / Build2400 / reserve120，共享5400秒 / 200工具 / 800万tokens，
至多一次同进程合作式续跑。未改运行条件，未重试、补位、运行 WebAgent 或查询公司平台。

最终独立审计 `passed/complete/final_acceptance=true`，root 再验 **251 项证据 SHA**，
报告与冻结 renderer 的原样输出一致。38 源码 / 122 冻结文件 / 36 历史锚点通过；源码
逐文件等于被测提交，074/076/078 的 68/105/205 份 Git 封存文件逐字节未变。没有运行
旧 live-source 审计。先前运行中的观察保持其原字节和时间点含义。

只读 watcher 33500 在两槽终止后退出 0，保存 172 份进度快照。进度间隔不是连续的主机
存活证明；其中 `plan_file_present` 也不替代独立审计的原生计划验收结果。

独立进程核验联合 190 份已保存身份/进度证据、10 个 PID / 5 个 PGID、可见后代、全
可见 argv 路径与 campaign/私有 case cwd 关联，未发现残留候选或检查失败；root 验证
全部 190 份支持证据 SHA，并再次确认数字 PID/PGID/后代范围为空。这是时点可见性
检查，保留 PID 复用、权限和未关联脱离后代等限制，不证明全局无残留或远端停止计费。

| 封存证据 | SHA256 |
| --- | --- |
| [最终独立审计](final-audit.json) | `5c8ed7fa586e1465a5da5c05535edf80ddf5689b6346789dafb33bb346492f4e` |
| [原样投影报告](final-report.md) | `e16347f83a2c791b550a82f6db1121c4abcf90e57a8cd2eaf0f236350429a13e` |
| [独立进程观察](final-process-observation.json) | `d2b61550c78666791390534e8ab71e7c3a0e91cbfbfcae12ebf55a6ffcf6f455` |
| [Root 收尾核验](final-process-check.json) | `506816ab2636f5480249e92b2493a3d79d51c7f366b818f362dbffb6d2f1af2a` |

本轮描述集成079/080/081后的实际行为，不隔离 deadline 的因果效果，也不倒推078根因。
两次尝试不能证明稳定性或相对 WebAgent 的效果优劣。Feature069普通流程的历史两例有效
结果保持为已有交付依据，不进入本轮分母。

## 后续方向

当前目标仍是分阶段完整交付并通过原生 harness。下一项应先明确新评测的主机保持唤醒
条件与时间口径，再设计单次请求预算和有限传输恢复；失败请求的未知 usage 必须有独立、
保守的预算及回执契约，不能简单捕获异常后继续花费。

[WebAgent 固定代码恢复机制比较](/Users/liminghan/Documents/lunar_agent/docs/webagent-transport-recovery-review-20260911.md)
已独立复核，可作为设计依据。它不授权重试本轮失败槽或评测其候选。本轮到此封存，
没有自动开启下一批 campaign。
