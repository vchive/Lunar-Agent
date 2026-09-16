# Feature 117：延长时限后的真实验收仍为 0/2

两项预登记任务均已运行一次，**primary completion 0/2，registered-envelope completion 0/2**。
没有冻结 evaluator、演化子任务、候选或交付；24 个 holdout 均未运行，官方 quality/gap
均为 null。本次没有恢复重试、澄清、补槽或模型回退。

## 登记与边界

- 登记提交 `17a0ad2f2f1138a9497c5ba92bb4f311428565b4` 先 push 后启动。
- 产品固定 `9a26a73e38d52b18f003b262a8746bb22496c156`，登记 SHA-256 为
  `822d46f6cc9bfd0850129bf4455bd32eb4652b7f9a07f3dabe9b4a8066b43ec2`。
- 76 项产品、15 项测量/测试、31 项历史文件指纹固定。原 115 的 14 项固定条件不变：
  同两题/顺序/输入、GLM-5.2/网关、population 2+1/seed 113、oracle 和 holdout 等。
- 单请求、普通 Agent invocation 和本地进程时限改为 600 秒，每题总时限改为 3600 秒。
  16 请求、160000 observed-token stop threshold 和四步工具上限保持不变。
- 产品与时限同时变化，不能把结果差异归因于某一项修复。仍无普通模式或 WebAgent 对照。

## 实际结果

| 任务 | 合同编译 | 后续阶段 | 进程总耗时 | 已知 tokens | 交付 |
| --- | --- | --- | ---: | ---: | --- |
| budget_selection | 成功，92.300 秒 | evaluator compiler 在 600.004 秒 HTTP 超时 | 693.420 秒 | 7601，小计 | 无 |
| worker_assignment | 响应在 36.108 秒返回，严格 JSON 校验失败 | 未进入准备 | 37.276 秒 | 3708，完整 | 无 |

两个进程均正常返回退出码 1；监督器确认清理通过，没有剩余已观察进程。两题 wall time
合计 **730.695 秒**。第一题请求耗尽的是单调用时限，并未达到每题 3600 秒总时限。

共三次模型请求，收到两次 glm-5.2 完整响应和一次 `transport_timeout`；超时阶段为
`open_response`，响应模型/usage 均不可得。已知用量小计 **11309 tokens**，其中 input
2337、output 8972。第一题超时请求消费未知，因此总消费和金额均未知；11309 不能当作
完整总量。调用日志没有 pending request，表示记录均有终结行，不代表全部消费已知。

## 状态修复在真实失败中生效

第一题父 run 为 `f0c1ad7e96744aa0885837212c582413`。Store 保留已接受合同和计划，
durable status 为 `running`；依赖任务 waiting，但没有任何非空问题。CLI 返回完整父任务
JSON：`status=failed`、`run_status=running`、`input_request=null`，stderr 为空。

`bundle_preparation_started` 与 `bundle_preparation_failed` 绑定同一次 attempt；CLI
`evolution.preparation` 与事件一致，stage 为 `evaluator_compile`、category 为
`runtime_error`、`recoverable=true`。这验证了 Feature 116 的诊断/状态改进。产品提供的
显式 resume 提示没有在此次测量中执行，任务仍按首次失败计入 /2。

第二题父 run 为 `3abc6aa1a0ad4558afb91696819867d2`，Store 与 CLI 都为 failed。
`contract-intake` 的持久错误是 `compiler response must be one strict JSON object`；
没有合同计划或准备事件。

## 响应诊断与局限

私有诊断保留两份完整响应文本，分别为 5435 和 8111 UTF-8 bytes；均无截断或脱敏替换，
文本 size/SHA 与原始记录一致。第一份严格重解析得到已保存合同。第二份外层是精确的
Markdown `json` 代码块，因此原始响应不是可接受的单个 JSON 对象。

仅作离线诊断，移除这一对外层代码块标记后，内部 JSON 能通过现有合同 schema 校验。
该解析结果没有写回产品 workspace、没有接入执行、没有改变失败结果或增加模型/评测器
调用。原始响应仍私有保留，不在公开报告中复制正文。不能据此声称第二题已经通过合同
编译或能够成功交付。

第一题的超时没有完整响应可供诊断。当前证据无法区分服务端长推理、排队、网关停滞等
具体原因，不能将其归因于某个提示或字段。延长到 600 秒仍未完成这次评测器请求，也不能
证明更长时限一定无效。下一步应优先处理已确认的合同输出协议可靠性，并离线审查评测器
输入/约束是否可验证；不继续用补槽或逐次加长时限替代问题定位。

## 后续离线代码审查

独立只读审查确认约束覆盖与可见证据范围不匹配：`evaluator_bundle.py` 的
`_validate_probe_suite` 要求每项 hard constraint 各有一个无效 probe，而 snapshot evaluator
不能读取候选源码或执行记录。第一题合同中的 `hc_stdlib_only`、`hc_two_source_files`、
`hc_exact_input_files` 均为 partial verification，且没有 result fields。相同输入和输出
无法区分单文件实现、第三方依赖实现或硬编码结果；内存验证也确认，只覆盖六项输出约束
会被现有完整覆盖规则拒绝。

后续应明确区分输出快照、源码交付和执行行为的验证范围，保留全部要求并分配给能够提供
相应证据的检查。不能仅因 partial 或空 result fields 就跳过约束；没有验证能力时应在
模型请求前报告不支持。现有源码文件计数不证明 helper 被调用，输入摘要不证明程序实际
读取过各输入，静态 import 检查也不能完整证明只使用标准库。这是独立代码问题；本次
evaluator 请求没有返回正文，不能据此认定超时原因。本审查没有修改产品或追加真实调用。

## 验证与证据

预启动 216 项相关离线测试通过，含 48 项新测试；本地 112 subprocess quickstart 完成
1、2、6、7 分交付，终态恢复调用数保持 1/1/1/4/4。独立预启动审查通过，见
[validation](../validation.md)。独立最终只读审查也已通过：41 个证据文件、10 条制品记录及
76/15/31 项登记指纹全部匹配，状态、失败和用量与现场一致。本功能没有产品代码修改，
不重复既有 5636 项产品全仓测试。

[results.json](results.json) 保留独立评分和固定分母；[diagnostics.json](diagnostics.json)
记录安全的实际状态/响应诊断；[evidence.json](evidence.json) 为私有现场 41 个文件的完整
size/SHA 清单。两题原现场保存在 `.lunar/acceptance117-glm-5.2-extended-deadline-20260916/`。
113、115 及更早冻结测量字节保持不变，各自 /2 单独报告，不能合并成一个可比总分。
