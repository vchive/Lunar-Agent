# Evolution ecosystem fusion roadmap（2026-09-11）

当前整体现状与版本完成标准见 [2026-09-16 系统评估](system-readiness-20260916.md)。
主线收敛为多文件评测、演化/交付接线、统一入口/恢复、当前版本真实验收四项；
Feature 108–112 已完成多文件评测、Agent 生成、原生 population、普通 solve 入口、自动
evaluator/profile 准备和父任务交付/终态恢复；Feature130已补完整合同封装示例并保持
strict parser；后续聚焦新的独立真实闭环，外部 producer 的多文件
接线与运行中取消编排仍未完成；
下文按日期保留实现过程，旧条目中的“下一步”以该评估和最新 HANDOFF 为准。

本文记录 Lunar-Agent 与公开 evolution/program-search 项目的融合边界和优先级。公开项目
信息核对于 2026-09-11；没有执行外部框架、模型、provider、远端服务、候选评测或真实
campaign。当前 Feature 084/085 建立 verified seed、population-first 和协议边界，Feature
086 又把已完成的远端 material observation 接到同一 exact-harness admission；仓库同时具备
OpenEvolve 的有界本地 subprocess producer 接线、ShinkaEvolve 的只读离线结果 exporter，以及
可供这些 producer 复用的 transport-free `ProducerResultEnvelope` → `SeedManifest` adapter。
这些接线只由离线 fixture 验证，不能据此声称真实框架已运行或任何项目的公开效果已由 Lunar
复现。

## 2026-09-17：合同响应完整封装示例

Feature130在isolated contract compiler提示中增加完整needs_input/compiled严格JSON示例，
两者显式status、分支字段互斥；compiled例经生产parser/dataclass验证。示例只说明shape，
任务内容须按当前goal/answer替换。生产parser与shape校验未改，contract-only仍拒绝，不推断
缺失status、不repair或retry。99项聚焦、104项相关回归和112恢复通过；全仓当前7168 passed/
1 skipped/24 deselected，固定旧产品24 passed，双阶段exit0。独立审查无问题。本轮无真实
请求，129保持0/1；下一次真实检查必须新登记并先push，不能重开旧槽。

## 2026-09-17：自动多文件验收暴露合同封装遗漏

Feature129固定产品b951857，先push独立登记08624f5后执行唯一原生多文件solve。合同请求
45.509秒HTTP200、4076tokens，但响应漏必需status=compiled，严格parser拒绝；没有进入
evaluator、候选或交付，primary/preparation/joint均0/1，0/8holdout执行。总47.339秒，清理
通过，官方quality/gap为null；没有重试、修补或额外请求。183项新测量测试、353项相关
回归及112恢复通过；见[129报告](../specs/129-small-multifile-acceptance/postrun/report.md)。
下一步补完整compiled/needs_input封装示例与离线请求检查，保持strict parser，不推断缺失
状态。128及更早结果不变，新真实验证仍需新登记；外部producer多文件接线与全链路取消后置。

## 2026-09-17：小型真实准备诊断通过

Feature 128 固定产品b951857，独立登记38c323c先push后运行唯一槽。compiler/auditor均
HTTP200，3项自测与5项独立探针通过，冻结1/1、预声明holdout8/8、联合1/1；总墙钟
507.148秒、记录用量完整43630tokens、费用未知、清理通过。209项测量测试、325项相关
回归与112恢复通过，63份保留证据、固定pins和历史字节复验通过。详见
[128报告](../specs/128-format-admission-diagnostic/postrun/report.md)。
这仅证明一次小型准备和整数留出一致性；没有solver/多文件交付，不证明通用正确性、
类型规则完整覆盖或126/127因果收益。下一步独立登记支持范围内的小型真实多文件任务，
贯穿自动合同准备、生成、执行、评分、选优和父任务交付。外部producer多文件接线与
全链路预算/取消仍后置，历史分母不变且旧槽不重开。

## 2026-09-17：本地准备失败细分

Feature 127 在原生检查位置产生compiler/auditor响应或preflight阶段、固定原因和有限数字
位置。自动准备通过既有失败事件持久化schema2/local_failure，JSON/文本status只展示复验
通过的详情；取消、终态、输入漂移和准备成功优先。旧记录、runtime恢复、严格审计/冻结
和模型提示不变，不保存生成内容或异常原文，不新增自动重试。process/response原因仍有
明确粗粒度边界。244项新测试及112恢复通过；最终当前6770 passed/1 skipped、历史固定
快照24 passed，整体exit0。见[127记录](../specs/127-evaluator-preparation-diagnostics/validation.md)。
下一步固定当前产品，另行登记新的小型真实诊断；125与所有旧槽不重开或补分。

## 2026-09-17：合成输入统一格式准入

Feature 126 复用真实画像的JSON/JSONL/CSV/text解析，在compiler/audit每组第一个probe
执行前检查全部声明输入，candidate/snapshot两种模式均覆盖。格式错误不再靠evaluator
自测发现；无效输出的输入仍须格式合法。小型/空数组/混合字段合成数据保留，不推断业务
schema，不复制私有统计。旧bundle保留既有身份和结构校验，不重新执行历史probe，
也不施加新增输入格式准入。
81项新测试、240项相关回归及112恢复示例通过，独立审查无问题；最终当前代码6526 passed/
1 skipped、固定历史快照24 passed，整体exit0。完整结果见
[126验证](../specs/126-synthetic-input-format/validation.md)。下一步补本地失败阶段和原因，
然后另行登记真实诊断。本轮未调用真实模型，125的0/1及所有旧分母不变。

## 2026-09-17：独立audit拦住输入结构误读

Feature 125 固定eefe389、登记ef29c36先push再执行独立/1诊断，保留123任务和预算。
compiler326.682秒后通过自测，auditor50.640秒返回，均HTTP200；本地准备拒绝，未冻结，
0/8holdout执行，最终freeze/joint0/1，用量完整36499tokens，清理通过。静态检查发现源码
把JSON整根当整数，3个自测输入也用了标量；audit的5个输入符合合同的{limit:整数}对象，
首个有效对象会被源码类型检查拒绝。audit阻止错误冻结，不重放或修补本次源码。
下一步复用真实输入的格式准入验证合成probe，补精确本地失败阶段；不推断任意业务schema，
不放宽审查。123与125保持各自0/1，旧四轮/2不改；尚无真实多文件交付或因果收益。
详见[125报告](../specs/125-snapshot-protocol-diagnostic/postrun/report.md)。

## 2026-09-17：补齐 snapshot 请求结构并验证实际路径

Feature 124 在共享compiler/auditor提示中给出完整request形状，明确runtime inputs[].target
和contract/profile/probe/output各处path的映射，直接读取已含output/的输出路径。占位示例
不重复任务上下文、不带主机路径；source_label与binding/evaluator字段只作元数据。
8项新增测试验证真实预检/生产请求、嵌套/零字节输入及可选输出缺失；独立构造的path误用
在audit/freeze前失败。88项相关回归和112恢复示例通过；24项历史登记测试依赖旧产品，
已用明确双阶段验证入口分配到固定快照，18项隔离/清理测试和CI接线完成。最终当前代码
6304 passed/1 skipped，历史快照24 passed，整体exit0。见
[124验证](../specs/124-snapshot-request-protocol/validation.md)。本轮未调用真实模型，四轮/2
与123的/1均保持原失败结果；下一步单独登记修复后的准备诊断，不重放旧槽。

## 2026-09-17：小型评测器诊断返回响应，定位本地接口误用

Feature 123 固定519fea5并先推送登记，单独/1诊断在242.848秒收到compiler HTTP200，
20831 tokens用量完整；随后本地准备失败，未调用auditor/freeze/8个holdout，最终0/1。
静态检查发现生成代码在inputs[]寻找path而非实际target，导致有效probe提前被判无效；
此前提示没有明确该嵌套字段，也未区分contract/profile中的path。下一步补齐真实snapshot
request示例并与本地产生的对象验证一致，保留此次失败且不重放旧槽。该证据不能解释120
超时或声称多文件闭环成功。见 [123报告](../specs/123-small-evaluator-diagnostic/postrun/report.md)。

## 2026-09-17：本地 HTTP 里程碑诊断

Feature 122 在不改请求、TLS/代理/重定向或时限的前提下记录最后本地连接/写入/响应头
里程碑和 HTTP 交换序号。接入 subject schema5，旧1–4仍可读；中间重定向状态不冒充
最终响应状态，连接阶段不声称能区分 DNS/TCP/TLS，写入返回不证明服务端已经执行。
本地测试后继续固定产品，下一步独立登记一项小型合成 evaluator 准备诊断（compiler一次，
只有原生校验通过才调用auditor，最多两请求），再检查冻结和预声明快照holdout。
这轮没有真实模型调用，四轮历史结果仍各自0/2；完整多文件真实交付仍待验收。
详见 [122验证](../specs/122-transport-milestone-observation/validation.md)。

## 2026-09-17：评测器生成协议补全

Feature 121 将完整 probe/file/ordering、报告嵌套结构与实际源码限制写入两种生成角色的
共享提示，并区分schema有效的业务反例与私有值恢复。51项离线测试通过；解析、模型调用
和冻结恢复不变。离线重建120的四个原请求，SHA匹配，未发现重复上下文；open_response
仍不能说明远端耗时原因。没有新的真实测量，四轮历史分母仍各自0/2。后续诊断须独立登记，
不靠反复加长时限或补槽。详见 [121验证](../specs/121-evaluator-prompt-protocol/validation.md)。

## 2026-09-17：支持范围真实验收仍为 0/2

Feature 120 先推送独立登记后运行两题，任务只要求可验证的 `python_file_count minimum=2` source check，保留数学输入/输出与117预算。两题合同编译成功，但 evaluator preparation 均在600秒 `open_response` 超时；无候选、交付或质量，已知用量16,161 tokens，费用和超时消费未知。113/115/117/120 各自0/2保持独立。不能把这次结果解释为旧 helper/import/input-read 语义或 WebAgent 对照。见 [120报告](../specs/120-supported-scope-acceptance/postrun/report.md)。

## 2026-09-17：源码文件数独立验证与完整交付

Feature 119 将显式的最少 Python 文件数要求接到独立评测、population 选优和父任务交付。
输出 compiler/auditor 只覆盖剩余输出约束，controller 根据已验证的完整源码 bundle 计数；
源码失败使候选无效，即使输出分数更高也不选用。完整检查证据随新协议交付并可只读重算，
旧无检查记录的协议/摘要保持兼容。离线自动 CLI 拒绝单文件 9 分结果，交付双文件 7 分，
终态恢复零新增执行；94 项新增测试见 [119 验证](../specs/119-source-file-verification/validation.md)。
这只证明文件数，不证明 helper 调用、运行依赖或实际读取输入。后续独立登记支持范围内的
真实闭环验收；不改写 113/115/117，也不将未完成的执行验证包装为通过。

## 2026-09-16：合同格式兼容与约束范围预检

Feature 118 接受完整的精确 JSON 代码块，但保留严格内部校验且不重试。约束新增显式
output/source/execution 范围，未声明的旧合同摘要不变。生成 evaluator 在请求前拒绝
没有独立检查能力的 source/execution 要求，持久保存 ID/scope 并向 CLI 说明，不再假装
输出探针能验证源码或运行行为。134 项新增离线测试通过，真实测量未重跑；见
[118 验证](../specs/118-contract-protocol-capabilities/validation.md)。下一步接入确实能验证的
源码交付要求，并在固定实现后独立登记真实闭环验收。执行依赖和真实输入读取仍不支持。

## 2026-09-16：延长时限验收与协议失败诊断

Feature 117 先以 `17a0ad2` 提交推送登记，在产品 `9a26a73` 上把单调用/进程限时增至
600 秒、每题增至 3600 秒，其余固定条件沿用 115。两题仍 **0/2**：预算选择通过合同，
随后 evaluator 编译在 600 秒超时；工作分配返回 Markdown JSON 代码块，严格入口拒绝。
内部 JSON 仅在离线诊断中确认 schema 有效，没有修复回填或重试。三次请求已知用量小计
11309 tokens，超时消费未知；无 evaluator、候选或交付。116 的完整失败 JSON、准备事件
和非用户等待状态在真实调用中生效。下一步优先合同输出协议可靠性及 evaluator 可验证
约束范围的离线检查；冻结旧槽，不用逐次加时替代定位。见
[117 报告](../specs/117-extended-deadline-acceptance/postrun/report.md)。

## 2026-09-16：准备失败状态与显式恢复

Feature 116 修复依赖等待误报用户待答，`answer` 只接收真实问题。自动 evaluator/profile
准备在模型调用前记录 attempt，失败保留安全阶段/类别；CLI 返回父任务 JSON 和非零退出，
`status` 可只读查询。已接受合同保留，运行异常可在输入/证据复验后显式 resume；不自动
重试，完整冻结 evaluator 与终态恢复不增加模型请求。中断开始记录为 unknown，取消与
完整性错误不承诺可重试。新代码仅离线验证，113/115 和 WebAgent 历史仍冻结；下一步
考虑独立登记新预算验收，而非重开失败槽。详见
[116 validation](../specs/116-preparation-recovery-state/validation.md)。

## 2026-09-16：修复后独立验收

Feature 115 固定 `5e2568f`，沿用 113 全部任务/模型/预算条件独立登记，两例完成仍为
**0/2**。预算选择通过合同编译后 evaluator 请求超时；工作分配合同请求超时。仅已知
8625 tokens，超时消费未知。见 [115 报告](../specs/115-isolated-intake-acceptance/postrun/report.md)。
下一步先修复 dependency waiting 误报用户等待和准备失败缺持久诊断的问题，不补旧槽。

## 2026-09-16：合同编译入口修复

Feature 114 将合同编译接到已有 stateless runtime 协议入口，消除普通 Agent 的最终总结
提示/工具与严格 JSON 编译要求的冲突，补全 evolution 等字段的明确类型和允许范围。
保留严格拒绝与澄清，不自动重试或宽松解析。离线请求与恢复测试通过；113 的真实失败
记录保持冻结，修复后效果必须另行登记，尚不能声称有效率已提高。

## 2026-09-16：首次当前版本真实验收

Feature 113 在提交/推送独立登记后，对 `c977eb4` 运行两例 GLM-5.2 自动多文件任务。
两例均在合同编译失败，完成 **0/2**，没有 evaluator、候选或交付。保留完整分母和已知
15958 tokens，不补槽、不重跑 WebAgent。见 [113 报告](../specs/113-real-multifile-acceptance/postrun/report.md)。
下一步先修复 compiler 误用普通 Agent 总结提示/工具的入口接线与 schema 指引，再以
新登记继续验收；外部 producer 接线继续后置。

## 2026-09-16：多文件 evaluator/profile 自动准备

Feature 112 新增 `solve --evolve --multi-file`，复用现有 evaluator compiler、独立 auditor、
约束反例和分数顺序探针，生成直接消费 108 输出快照的评测器。保持旧单文件调用模式，
不伪造旧 candidate/execution 文件。准备完成后保存普通 pipeline profile 和六份冻结材料，
绑定当前输入、contract、字节摘要与 artifact rows；恢复/answer 自动识别模式，已有冻结
评测器不再调用 compiler/auditor。普通 `deliver` 同样复验准备材料。

可运行 [112 quickstart](../specs/112-automatic-bundle-evaluator/quickstart.md) 不需要显式 profile，
使用本机 subprocess 完成完整链路。自动准备仍受原编译器输入格式和探针容量限制；探针
通过不等于完整业务正确性或真实模型效果。接下来应先独立登记小规模当前版本验收，观察
有效率、质量、耗时和用量，再根据结果处理缺陷或外部多文件 seed 接线，不以新增协议
替代真实验证。历史 WebAgent/失败测量不重跑、不改写。

## 2026-09-16：普通任务入口与多文件父任务交付

Feature 111 增加 `solve --evolve --bundle-profile PROFILE --input SOURCE[=TARGET]`，复用正常
contract intake、原生 runtime 和完整 bundle Agent。profile 与父任务已登记输入精确匹配，
演化读取父任务 staged bytes。选优后直接交付已评分的输出快照，完整源码与评测材料保留在
父任务 `.bundle-deliveries/`，普通 `deliver` 可验证并返回。终态恢复复用既有 child/copy/output
journal；`answer`、`resume` 和不带 `--evolve` 的 solve 恢复都要求相同 profile。

可运行 [111 quickstart](../specs/111-conversational-bundle-delivery/quickstart.md) 使用本机
subprocess 同时完成 intake 和候选生成，不调用真实模型/框架。固定 evaluator 仍需显式
准备；profile 原始输入/harness 资源须可复验。运行中取消、detached bundle solve、自动
evaluator 准备和外部 bundle seed 接线继续后置。新真实测量仍需独立登记并保留失败分母。

## 2026-09-16：Agent 自动多文件生成

Feature 110 将 `AgentCandidateGenerator` 接入 bundle pipeline。用户可选择 Agent command
或 native runtime，Agent 在新工作目录读取完整父代源码、已验证输入和独立评分反馈，
返回完整源码 map；固定的本地 evaluator 继续独立评分。大源码通过完整 context 文件读取，
提示词保留有界摘要，评测器实现不进入 solver context。CLI 的 generation 模式与设置参与
恢复身份，原 command 模式保持兼容，terminal resume 不再调用 Agent 或候选。

本地 command/subprocess runtime fixture 和完整交付已提供可运行
[110 quickstart](../specs/110-agent-bundle-generation/quickstart.md)。这一轮不运行真实模型或
外部框架，不能作为真实效果增益。正常任务路由、evaluator 准备和统一恢复继续接线。
已按用户新指示推送已验证的工作，后续不再长期积累本地提交。

## 2026-09-16：多文件原生 population 与完整交付

Feature 109 已通过 `MultiFileCandidatePipeline` 复用原生 population/archive：完整源码 map
经过 103–108 的物化、执行和独立评测，再发布 v2 receipt；旧 v1 数据与摘要保持兼容。
本地 command producer 可以读取完整 parent 源码并只修改 helper。谱系、代数、island、迁移、
有效性优先选优和 checkpoint 沿用已有搜索循环；同一 execution/evaluation 不能冒充多个候选。
失败/未知尝试保留原目录，terminal resume 只复验，不追加执行。

`evolve-bundle` 提供一条显式入口完成生成、评分、选优及可选交付。Controller 校验 Store
绑定的选择结果后，交付完整源码、已评分输出快照、输入与 evaluator 材料，独立 byte manifest
支持复制后的只读检查。原 107/108 inode-bound 证据保留原位。可运行样例见
[109 quickstart](../specs/109-bundle-population-integration/quickstart.md)。

这完成了本地多文件闭环；普通任务自动路由、Agent 自动生成多文件与 harness、parent-run
交付/统一恢复以及 OpenEvolve/Shinka 的多文件 seed 导入继续后置接线。本轮没有新真实模型
或外部框架运行，不能把 fixture 分数视为当前版本效果提升。

## 2026-09-14：CLI 热启动入口

Feature 096 已把现有离线 adapter 接到用户入口：`export-shinka-result` 导出静态 Shinka
结果；`evolve --producer-result ROOT --producer-fingerprint SHA` 将兼容 envelope 交给
Lunar population 的同一 exact-harness seed admission。新共享 API
`prepare_producer_seed_manifest` 只做只读校验与内存 manifest 构造，准备阶段不评测、
不创建 Candidate 或 receipt。CLI 支持固定 producer pin、可选名称 pin、正常 resume
fresh revalidation 和 detached 参数传递。使用方法见
[096 quickstart](../specs/096-producer-cli-warm-start/quickstart.md)。

该入口已用 SQLite + 本地 generator/evaluator fixture 验证，未启动真实 Shinka、模型或
远端服务；不构成框架效果比较。下一层仍是 SkyDiscover/LLM4AD benchmark/task envelope
与固定条件下的独立测量，多文件/repository/workflow candidate 另立契约。

## 2026-09-14：benchmark/task envelope

Feature 097 adds the offline `lunar-benchmark-task-v1` envelope and static
`benchmark-task validate` command. It binds task, contract, input bytes, model/evaluator identities
and physical budget for future SkyDiscover/LLM4AD comparisons. Admission is read-only and external
scores or generation IDs never become Lunar scores or iterations. No external framework or model is
launched; comparisons still require fixed conditions and a new pre-registered measurement.

## 2026-09-15：fixed-condition comparison plan

Feature 098 adds `BenchmarkComparisonPlan` above the task envelope. It freezes common workload,
contract, model, evaluator, candidate and physical budget across two or more arms, then performs
read-only input/pin admission. This is preparation for later SkyDiscover/LLM4AD comparisons; no
framework execution or effectiveness claim is included.

## 2026-09-16：多文件候选 bounded runner

Feature 108 已补上独立评测入口：成功的 execution record 经身份和字节复验后，把声明
输入/输出复制到新 evaluation 目录；固定指纹的 harness 仅读取快照，返回严格评测报告。
输出格式不合格时直接给出无效零分，不启动 harness。保存原始报告和绑定快照的 manifest，
`inspect-evaluation` 只读复验，不重跑候选。输出观察明确发生于评测时，不冒充执行退出时
的输出证明。双文件本地样例和边界 fixture 已通过；尚未接入 Candidate/receipt/archive、
population/controller 与恢复交付，没有新增真实模型或外部框架效果结论。

Feature 107 已在 runner 之上完成独立执行证据层：`candidate-bundle run-recorded` 先独占
新 attempt 目录并同步 launch intent，再执行一次 Feature 106，最后绑定 result/completed
文件的 SHA-256、size 和 inode。`inspect-execution` 只读复验原 plan/admission 与记录；
缺完成记录或保留临时文件时返回 uncertain，同一 attempt 不自动重跑。真实双进程争用与
五个 os._exit 崩溃阶段已有本地 fixture 覆盖。该层不复用旧单文件 Store 状态机，不登记
Candidate、不评分、不提供 attestation 或 resume。下一项优先把完整多文件执行记录与
exact evaluator 的输出契约关联，再进入 receipt/archive；真实固定条件效果测量仍未完成。

Feature 106 consumes the verified workspace plan, execution admission and staged input directory
with a single bounded local process invocation. It revalidates immutable declarations and mutable
bytes immediately before launch, rejects symlinked or overlapping roots, uses explicit argv plus the
bundle entrypoint, and bounds stdout/stderr while terminating the process group on timeout or output
overflow. The static `candidate-bundle run` command is dispatched before normal Store/home setup.

This is an execution boundary only. It accepts `max_processes == 1` as the current admission subset,
does not monitor candidate-created forks, and does not produce durable execution evidence, invoke an
exact evaluator, create Candidates, or resume interrupted work. A zero exit code cannot be used as a
Lunar score or as evidence of OpenEvolve/WebAgent parity. Those concerns require a later launch-intent,
evidence and evaluator feature; no external framework, model, provider or campaign was run here.

## 2026-09-15：comparison result receipt

Feature 099 adds a bounded result envelope for future fixed-condition measurements. It binds each
per-arm summary to the 098 plan and preserves only evidence digests and finite summary metrics;
parsing is read-only and does not run or score any external framework.

## 2026-09-15：comparison evidence binding

Feature 100 optionally adds a relative evidence path and byte size to each 099 arm result. When an
operator supplies an evidence root, Lunar verifies confined non-symlink regular-file bytes,
stable device/inode, exact size and SHA-256 before accepting the receipt. Digest-only 099 results
remain compatible without an evidence root. This binds a receipt to observed local bytes but does
not certify the producer, evaluator or framework, and does not create a benchmark effectiveness
claim.

The Feature 100 follow-up replaces separate path checks/opens with bounded descriptor-relative
reads for result JSON and evidence. It also rejects observed file or directory replacement,
same-size rewrites, malformed scalar fields and null explicit binding roots. Legacy digest-only
receipt identities remain compatible; result/evidence paths now share the strict no-symlink boundary.

## 2026-09-15：exact comparison plan binding

Feature 101 adds a complete canonical plan pin to new result receipts. It rejects reuse after a
same-named arm changes benchmark release/publication or swaps its envelope with another arm. The
explicit caller pin can require that binding; legacy receipts remain readable with `plan_bound:
false`. Plan/task DTO replay and bounded descriptor reads cover the static admission path. This is
measurement preparation, not a live experiment or evidence that external frameworks improved results.

## 2026-09-15：多文件候选源码包

Feature 102 新增独立 `CandidateSourceBundle` 和静态 `candidate-bundle validate` 命令，
为多文件候选建立 contract、entrypoint、每文件路径/大小/摘要以及完整 bundle digest。
只读验证有界 UTF-8 源码，拒绝路径冲突、symlink 和观察到的文件变化；显式 bundle pin
可以固定整个声明。此阶段只覆盖声明的源码文件，不等同 repository 快照、依赖/环境
认证或执行回执，也不转换现有 Candidate、SeedManifest 或 producer envelope。

后续仍需定义独立 workspace 中的多文件执行、输入/依赖/环境契约、exact evaluator、
receipt/archive/resume 关联，之后才可接 DGM 等 repository producer。ADAS/EvoAgentX
的 workflow graph 也需要独立候选契约。真实框架对照测量仍未完成，本功能无效果结论。

## 2026-09-15：候选源码 workspace 物化

Feature 103 新增 `candidate-bundle materialize` 和独立 workspace plan。它把 Feature 102
已验证的声明文件复制到新建私有目录，逐文件重新校验并在失败时清理半成品；plan 绑定
bundle/contract、entrypoint、文件表摘要、显式 runner、超时、输出上限和环境摘要。命令不
执行 entrypoint、不初始化 Store/home，也不产生 Candidate、receipt 或 archive。多文件执行、
exact evaluator、依赖/环境真实性和恢复关联仍需后续 Feature。

## 2026-09-16：Feature 104 candidate execution admission（已完成静态 admission 边界）

已冻结草案位于 [specs/104-candidate-execution-admission](../specs/104-candidate-execution-admission/)。
它承接 Feature 103 的 path-free workspace plan，现已实现 immutable DTO、canonical admission
digest、完整 plan/bundle/contract 与 caller pin 校验，以及可选的 bounded no-follow 输入字节
复核。声明绑定逻辑输入文件的目标/大小/SHA-256、dependency/environment identity、exact
evaluator pin、output-contract pin 和有界 process budget；输入 root 不提供时仍可执行纯内存
结构 admission。所有 pin 在输入文件 IO 前校验，输出只含身份、计数、限制和摘要。

该层只产生静态、可重放的 admission digest，不启动命令、不 import 候选、不安装依赖、不
调用 evaluator、不初始化 Store/home，也不写 Candidate、receipt、archive、resume 或
materialization ledger。Feature 104 focused suite 当前为 **195 passed**（含 installed CLI fixture）；
全仓回归为 **4471 passed, 1 skipped**；这些是离线协议验证，不构成任何框架效果结论。

静态 `candidate-bundle admit-execution` CLI 已在普通配置/Store 初始化之前分派，并覆盖
installed-CLI 的 no-home/no-execution、pin mismatch 和输入字节校验。后续仍需独立 Feature
处理真实 runner、exact evaluator、execution evidence 与恢复协议；input staging 由下述
Feature 105 实现。

## 2026-09-16：Feature 105 candidate input staging

新增 `stage_candidate_execution_inputs` API 和静态 `candidate-bundle stage-inputs` CLI。
它先重验完整 admission、plan 和 caller pins，再将声明的输入复制到新的 `.candidate-inputs-*`
私有目录。输入支持二进制、嵌套目标和空文件；源/目标根按实际目录身份检查，目标逐个重读
size/SHA-256。失败或中断时只清理本次创建且身份仍匹配的内容，清理无法安全完成时返回固定
错误。输入使用新建目录，不合并到源码文件表，也不复制未声明文件。

返回元数据只含摘要、计数和大小；本地 `input_path` 单独提供给调用方。重复调用生成不同
目录，没有自动复用、恢复或执行回执。Feature 105 的 **96** 项测试、installed CLI 及可运行
示例均通过；全仓 **4568 passed, 1 skipped**。详见
[Feature 105 验证记录](../specs/105-candidate-input-staging/validation.md)。

下一步仍需实现消费源码 workspace、staged inputs 和 admission 的真实 runner，再接 exact
evaluator、execution evidence 和恢复协议。本功能没有运行真实模型或框架，不产生效果结论。

## AlphaEvolve 与 OpenEvolve 的关系

[AlphaEvolve](https://deepmind.google/discover/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/)
是 Google DeepMind 公布的系统。[官方结果仓库](https://github.com/google-deepmind/alphaevolve_results)
明确说明它不包含运行 AlphaEvolve 的代码；DeepMind 另行公开了
[问题仓库](https://github.com/google-deepmind/alphaevolve_repository_of_problems)。因此不能把任何
第三方仓库描述为 DeepMind 官方实现或完整、逐行复刻。

[OpenEvolve](https://github.com/algorithmicsuperintelligence/openevolve) 的仓库描述是
“Open-source implementation of AlphaEvolve”。它是 Apache-2.0 的第三方开源实现，采用
LLM 生成、MAP-Elites、quality-diversity、多岛迁移、外部 evaluator 和 checkpoint 等思路。
它与 AlphaEvolve 方向一致，适合作为 Lunar 的首个本地 subprocess producer，但其分数、
数据库和 checkpoint 都不自动成为 Lunar 的权威状态。

ShinkaEvolve 的 native 结果可通过 `src/famou/shinka_handoff.py` 导出到同一 envelope。该
exporter 只读查询 `programs` 表中固定的 `id`、`code`、`language`、`parent_id`、`generation`、
`combined_score`、`correct` 字段，并显式兼容 `programs.sqlite` 与旧的 `evolution_db.sqlite`
文件名；有 live `-wal`/`-shm`/rollback-journal sidecar 的数据库会被拒绝，避免只读打开产生
副作用。调用方可按顺序指定 `program_ids`，此时省略 `top_k`；不指定时，`top_k` 默认一条，
只选择 `correct = 1` 的 convenience rows，并按 producer score、generation、ID 确定性排序。
导出目标要求是不存在的新 leaf，已有 parent 必须是无任意 symlink 组件的目录。源文件优先是
`gen_<generation>/main.<ext>`，仅在该文件缺失时回退到 `best/main.<ext>`，且必须和数据库
`code` 的 UTF-8 字节完全一致。导出后的 envelope 仍须经过 `admit_producer_result` 和
Lunar exact evaluator；Shinka 的 score、correct、metrics、generation 与 SQLite 元数据只归一化
为 digest-only external evidence，parent IDs 只作有界 lineage，不获得 Lunar 的 score、rank
或交付权限。当前只用离线 fixture 验证，未运行真实 Shinka、模型、网络或 Slurm。

Feature 086 的 `remote_material_handoff` 复用这条边界处理 Feature 084 的
`RemoteExperimentState`：只有经过可选 previous-state reconciliation、身份 pin 匹配、状态为
`completed` 且带有 `candidate_source` 的 observation 才能在内存中转换为 producer envelope。
本地 material root 仍由 descriptor-based regular-file、大小、UTF-8、路径 confinement 和
SHA-256 检查保护，随后统一调用注入的 exact evaluator。远端 ID、时间戳、attempt 和任何
score-like evidence 只保留摘要；bridge 不含网络、subprocess、scheduler 或 backend 调用。

## 项目映射

| 项目 | 公开定位 | 对 Lunar 的合适接法 | 优先级 |
|---|---|---|---|
| [OpenEvolve](https://github.com/algorithmicsuperintelligence/openevolve) | AlphaEvolve 风格的程序演化，Apache-2.0 | 先做隔离 subprocess material producer；也可选择性移植 MAP-Elites、双重选择和多岛机制 | P0 |
| [ShinkaEvolve](https://github.com/SakanaAI/ShinkaEvolve) | 面向开放式、样本高效程序演化，Apache-2.0；有 runner、CLI、并行评测和 Slurm 路径 | 以独立进程或远端作业产出程序与 lineage，再走同一 seed admission | P0 |
| [EoH](https://github.com/FeiLiu36/EoH) | Evolution of Heuristics，MIT | 将 selection/reflection/heuristic mutation 抽成 Lunar 原生策略模块 | P1 |
| [ReEvo](https://github.com/ai4co/reevo) | reflective evolution hyper-heuristic，MIT | 借鉴 reflection 与候选改写策略，评分仍使用 Lunar evaluator | P1 |
| [FunSearch](https://github.com/google-deepmind/funsearch) | LLM 程序搜索示例，Apache-2.0 | 借鉴程序库、采样和 evaluator 驱动的搜索；不作为 AlphaEvolve 后端 | P1 |
| [GEPA](https://github.com/gepa-ai/gepa) | reflective prompt/code optimization，MIT | 注册为文本、prompt 或代码 mutation 策略；需要显式候选类型 | P1 |
| [LLM4AD](https://github.com/Optima-CityU/LLM4AD) / [LLM4AD Next](https://github.com/Optima-CityU/LLM4AD_Next) | 自动算法设计平台，BSD-2-Clause / BSD-3-Clause | 优先作为算法比较和 benchmark 适配层，选定模块再原生化 | P1 |
| [SkyDiscover](https://github.com/skydiscover-ai/skydiscover) | 优化、合成与统一 benchmark，Apache-2.0；仓库内含 AdaEvolve/EvoX 并支持比较多个框架 | 先接 benchmark/task envelope；AdaEvolve 没有独立官方仓库，不能假设单独 adapter | P1 |
| [Darwin Gödel Machine](https://github.com/jennyzzt/dgm) | 开放式自改进 coding agent，Apache-2.0 | 等 Lunar 定义多文件 repository candidate 和隔离执行后再接 | P2 |
| [ADAS](https://github.com/ShengranHu/ADAS) | 自动设计 agentic systems，Apache-2.0 | 需要 agent graph/workflow candidate、运行回执和结构化 diff 后再接 | P2 |
| [EvoAgentX](https://github.com/ANative-Lab/EvoAgentX) | 构建、评估并演化 Agent/workflow，MIT | 作为上游 workflow producer；不能压成单个 Python candidate | P2 |
| [MLEvolve](https://github.com/InternScience/MLEvolve) | 端到端机器学习算法发现，Apache-2.0 | 先以完整实验后端导出 material；训练数据、环境和成本身份需单独契约 | P2 |
| [ThetaEvolve](https://github.com/ypwang61/ThetaEvolve) | 面向 test-time learning/RL 的 AlphaEvolve 扩展，Apache-2.0 | RL checkpoint、训练环境和资源账本成熟后再接 | P3 |

优先级表示接口适配顺序，不表示算法效果排名。仓库自述的 benchmark、SOTA 或可复现性
不能替代 Lunar 在固定 contract、预算、模型、输入和 exact harness 下的对照测量。

## 三层融合方式

### 1. Material producer adapter

`src/famou/producer_handoff.py` 提供通用的 `ProducerResultEnvelope`、`ProducerMaterial`、
`admit_producer_envelope` 和文件入口 `admit_producer_result`；它为有稳定 CLI/runner 的框架定义一个共享 material 边界，不要为每个
框架增加一套 Lunar strategy 状态。请求只包含固定 contract digest、bounded budget、run-scoped
output root 和 producer identity；结果只允许包含 terminal/unknown 状态、opaque producer run ID、
候选 material `{path, size, sha256}`、lineage 和 bounded external evidence。所有外部 evidence
与 record metadata 在进入 Lunar canonical state 前统一变成
`{present, score_present, payload_sha256}`，不保存原始分数或 prose。

producer 产物统一转换为 Feature 084 `SeedManifest`。Lunar 在自身 workspace 内重验候选源
路径与字节摘要、声明的依赖/环境身份和 evaluator fingerprint，然后调用本地
`exact_harness`。`material_refs` 只是带规范化列表摘要的 opaque 引用；除非具体 adapter
另行取回并校验相应物料，不能把该列表摘要描述成物料字节验证。只有生成匹配
receipt 且 `validity == 1` 的 material 才能成为 `Candidate`、进入 archive/population、参与
rank 或最终交付。外部 score 只保存为 provenance；producer 不得直接构造 Lunar
`EvaluationReport`。

这层适合 OpenEvolve 和 ShinkaEvolve，也是其他 CLI 兼容框架的默认接入方式。每个具体
adapter 至少要满足：版本/配置可生成稳定 fingerprint、候选可导出并校验摘要、输出有界、
timeout/cancel 受控、未知结果可区分，而且集成不需要信任其 score。

### 2. Lunar-native algorithm modules

对只需要算法思想的项目，移植 selection、mutation、crossover、reflection、MAP-Elites、
island/migration、novelty 或 retry 机制。模块输入输出使用 Lunar 的 `Candidate`、
`GenerationRequest` 和 `EvaluationReport`，继续由 Lunar 管理 budget ledger、archive、
checkpoint、resume 和 evaluator authority。这条路径适合 EoH、ReEvo、FunSearch、GEPA，
以及 OpenEvolve/SkyDiscover 中经独立基准证明有价值的局部机制。

算法移植必须保留正式 iteration 的语义：至少一个 offspring 完成生成和评估才推进；失败、
timeout、unknown 与无效候选分开记录。不能把外部框架的 retry 次数、generation 或数据库
序号直接映射为 Lunar iteration。

### 3. Remote backend/control plane

长时、集群或服务化框架使用 Feature 084 的 `RemoteEvolutionBackend` 生命周期：
`submit`、`status`、`sync`、`continue_experiment` 和 `cancel`。请求绑定 bundle、预算、producer
和幂等身份；超时、断连或缺少实验 ID 时保持 `unknown`，先 reconcile，禁止盲目重建。
`sync` 只带回 material 和外部 evidence，随后仍回到第一层的本地 exact-harness admission。

Feature 086 的 bridge 是这一回路的离线最后一跳：它只接受 caller 已经取得并 reconciled 的
completed state 和本地同步文件，不执行 `sync`，也不把 completed 生命周期状态解释成
`EvaluationReport`。因此 remote backend 的未知、失败或取消状态仍然只能停在生命周期层。

famou-v2/WebAgent 风格控制面、Slurm ShinkaEvolve、MLEvolve 或其他远端实验适合这一层。
默认 population 构造不能自动联网、发现服务或实例化 remote backend。

## 两种 OpenEvolve 用法必须分开

- `--strategy openevolve` 表示本次搜索由 OpenEvolve producer 执行；最终 Lunar candidate 和
  result 保留 `openevolve` 策略身份，但仍需本地 receipt 才能交付。
- OpenEvolve 结果也可以通过 seed manifest 成为本地 population warm start；此时 candidate
  的策略身份是 `population`，`producer_id=openevolve`、producer fingerprint 和 run ID 留在
  provenance 中。

两条路径可以共用 material、receipt 和 admission 组件，但不能把 population placement
字段硬编码进通用 producer 结果，也不能把 OpenEvolve 的外部分数作为快速通道。

## 实施顺序

1. 完成 Feature 084 的原子 mixed-batch admission、receipt 持久化、fresh revalidation 和
   resume fingerprint 校验；完成 Feature 085 的 population-first 默认及历史 loop 只读边界。
2. 把现有 OpenEvolve one-shot wrapper 收敛为首个 `EvolutionMaterialProducer`，补 producer
   fingerprint、lineage、bounded output、timeout/cancel 和同一 exact-harness receipt；当前
   wrapper 与通用 envelope 均已由离线 fixture 验证。
3. 已用固定离线 fixture 验证 ShinkaEvolve 的显式 best/program exporter、OpenEvolve producer
   输出和 completed remote material observation 能进入同一 `lunar-producer-result-v1` admission；
   不启动真实模型或外部框架。
4. 为 SkyDiscover/LLM4AD 增加 benchmark/task envelope，使用相同 contract、输入、模型、
   evaluator 和物理尝试预算进行比较。
5. 只移植经上述对照有收益的原生算法模块。多文件、Agent/workflow、训练型候选和远端服务
   各自进入后续冻结 Feature，不扩张单文件 seed schema。

完成这些边界只证明互操作和评分权威一致，不证明任何框架提高 Lunar 的有效解率。效果结论
需要新的预注册真实测量；历史 Feature 051/074/076/078/082 的 protocol、manifest、receipt
和统计保持原字节。普通 offspring/candidate 的完整 receipt、contract/evaluator/dependency/
environment fingerprint 后来已由独立 Feature 087 完成，未混入 Feature 086 的 archive
schema。
