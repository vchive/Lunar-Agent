# Lunar-Agent 交接记录

## Feature 104：候选 execution admission（已完成静态 admission 边界，2026-09-16）

已实现 `src/famou/candidate_execution.py` 的静态、path-free admission API：
`CandidateExecutionInput`、`CandidateEvaluatorPin`、`CandidateExecutionBudget`、
`CandidateExecutionAdmission`、`VerifiedCandidateExecutionAdmission`，以及
`build_candidate_execution_admission`、`parse_candidate_execution_admission`、
`validate_candidate_execution_admission` 和 `admit_candidate_execution`。声明绑定完整
Feature 103 workspace plan digest、bundle/contract、排序后的逻辑输入描述、非零
dependency/environment commitments、exact evaluator pin、可选 output-contract digest 与
有界 timeout/output/input/process budget；canonical digest 不含本地路径和自身 digest。

结构 parse/validate 完全内存内进行。可选 `input_root` 使用已有 descriptor-based no-follow
reader，对每个声明文件做有界 size/SHA-256 复核，并在任何输入 IO 前校验 plan、bundle、
contract、dependency、environment、evaluator、output-contract 和 admission caller pins。
省略 `input_root` 时 `observed_inputs` 为 `None`。该层不启动 runner、不 import 候选、不安装
依赖、不检查 host environment、不调用 evaluator、不初始化 home/Store，也不写 Candidate、
receipt、archive、resume 或 materialization ledger；它不是执行回执。

Feature 104 focused 测试当前 **195 passed**（含 installed CLI fixture）；全仓回归
**4471 passed, 1 skipped**，Ruff、compileall 和 diff check 已通过。静态
`candidate-bundle admit-execution` CLI 已在普通配置/Store 初始化之前分派，并覆盖成功、输入
size/hash、plan/pin mismatch、entrypoint 不执行及 no-home/Store。不要把它描述成真实
候选执行、模型、evaluator、OpenEvolve/WebAgent 或效果测量。

## Feature 103：候选 workspace 物化（已完成，2026-09-15）

已冻结并开始实现独立的 `candidate_workspace.py`：将 Feature 102 已验证的多文件 bundle
复制到新建私有目录，逐文件 no-follow 有界读取、独占写入、fsync 和目标重读校验，失败清理
全部临时目录。`CandidateWorkspacePlan` 绑定 contract/bundle、entrypoint、排序文件表摘要、
显式绝对 runner、空默认环境、超时和输出上限；不含本地 workspace 路径。

静态命令为 `candidate-bundle materialize MANIFEST --source-root ROOT --contract CONTRACT
--workspace-root ROOT --command /usr/bin/python ... --json`。它不启动进程、不 import/evaluate、
不初始化 Store/home、不写 Candidate/receipt/archive，也不改变现有 Candidate、SeedManifest
或 materialization ledger。聚焦回归 `266 passed, 1 skipped`，Ruff 和 compileall 通过；安装 CLI
fixture 已确认只复制声明文件、入口不执行且不创建 home。全仓回归与本地提交已完成，未 push。

Feature 104 已完成 admission API、静态 CLI、installed-CLI side-effect fixture 与最终全仓回归。
详见本文件顶部 Feature 104 记录；它仍是静态声明，不是 runner 执行能力。

## Feature 102：多文件候选源码包（已完成，2026-09-15）

新增独立 `CandidateSourceBundle`，把问题 contract、entrypoint 以及每个声明源码文件的
路径/大小/SHA-256 绑定到完整 canonical bundle digest；按路径排序，不受 JSON 格式或
文件声明顺序影响。公开 parse/validate/verify API 深层重建 DTO；要求 contract pin，
可选 caller bundle pin，两者在源文件 IO 前检查。返回 bundle 元数据、文件数和总字节。

文件限定 1–64 个、每个 0–1 MiB、总计 ≤16 MiB；manifest ≤128 KiB。路径必须是 NFC
相对 POSIX，拒绝 traversal、控制/格式字符、`.git` 组件、大小写组件别名和文件/目录
前缀冲突。空文件合法，源码只接受无 NUL 的 UTF-8。复用共享 descriptor reader，
有界读取且拒绝 symlink、非 regular file、大小/hash 漂移和观察到的文件/目录替换。

新命令 `candidate-bundle validate MANIFEST --source-root ROOT --contract FILE
[--bundle-sha256 SHA] --json` 在普通配置初始化之前分派，只输出 status、两个摘要和
文件数/字节数，不创建 home/Store，不执行、导入、评测或登记候选。contract 文件也使用
同一有界 no-follow reader；现有单文件 Candidate、SeedManifest、producer schema 不变。

新增三文件 **159 passed**（核心 84、独立文件边界 45、CLI 30）；和全部 benchmark 联合
**346 passed in 0.73s**。独立终审无 blocker，实际安装 CLI quickstart 双文件/131 bytes
验证成功，helper 同大小改写被拒绝，home/执行 marker 均未创建。全 src/tests Ruff、
compileall、Specify 与 601 个历史封存文件对照均通过。全量 **4169 passed in 202.02s**，
JUnit 确认零失败/错误/跳过；本轮统一在本地 `main` 提交，不 push。详情见
`specs/102-candidate-source-bundle/validation.md`。

本功能只验证声明的源码字节，不扫描未列文件，不保证多文件原子快照、import closure、
依赖/环境、producer 身份、语法或算法有效性。未运行真实框架、模型、provider、WebAgent、
远端服务或 campaign，无新增算法效果结论。下一步需独立设计多文件 workspace 的执行、
输入/依赖/环境契约与 exact evaluator/receipt/archive/resume 关联，再接 repository
producer；workflow graph 候选和真实固定条件对照测量仍未完成。

## Feature 101：comparison receipt 完整计划绑定（已完成，2026-09-15）

099/100 的 comparison ID 只绑定共享条件，原先即使同名 arm 换 benchmark 版本、发布摘要
或互换 envelope，旧 receipt 仍可能通过。现新增可选 `plan_sha256`，绑定完整规范化 plan
（含 arm ID 与 benchmark name/release/publication 的关联），并参与 result ID。合法无 pin
的 099/100 JSON、result ID、digest 已用 `d81145f` golden values 验证保持兼容。

新工厂 `BenchmarkComparisonResult.from_plan(plan, arms)` 在无 IO 的结构复验后显式创建
带 pin 的 receipt；不替旧 receipt 自动补 pin，也不代表此前已运行过该计划。API 的
`expected_plan_sha256` 与 CLI `benchmark-comparison validate-result --plan-sha256 SHA`
要求 caller pin、receipt pin 和完整 plan digest 全部匹配；legacy receipt 无法满足该请求。
输出分别给 `plan_bound`、`evidence_bound` 和 canonical `plan_sha256`，避免混淆计划关联
与实际证据字节校验。pin 是 canonical plan digest，不是格式化 JSON 文件的原始字节摘要。

新增 `validate_benchmark_comparison_plan`，深拷贝重验 plan 结构及所有 arm 的共同身份。
task admission 同样重建 DTO，拒绝内存对象被改为 root 外路径、超限大小或非法 schema。
100 的 fd reader 已抽到私有 `_benchmark_files`，task/plan/result/evidence 和公开输入共用
no-follow、有界读取及读后文件/目录名复核，保留各 API 固定错误码。task/plan/input 也采用
无祖先 symlink、无 `..`、4096 UTF-8 字节/128 绝对组件边界；单输入仍限 16 MiB。

新增四文件共 91 项；所有 benchmark 测试 **187 passed**。全量 **4010 passed in
229.10s**，JUnit 确认零失败/错误/跳过；全 src/tests Ruff、compileall、Specify、diff
check 通过。独立终审无剩余 blocker，实际安装 CLI fixture 已验证双绑定成功、版本变化
拒绝且不创建 home。051/074/076/078/082 的 601 个封存文件相对 `027a235` 未变。

README、architecture、roadmap、101 specs 和 Specify 当前 feature 已同步。仅本地 `main`
提交，不 push；未运行真实框架、模型、provider、WebAgent、远端服务或 campaign，不新增
算法效果结论。该 pin 只覆盖当前 DTO 已表达的字段，不认证 producer、未表达的命令/配置
或真实测量；文件检查不是多文件原子快照。真实对照测量与多文件/repository/workflow
candidate 契约仍未完成，后续另行设计。

## Feature 100 补修：有界证据读取与文件替换检测（已完成，2026-09-15）

复核发现原实现检查路径后再打开文件，期间发生文件/目录替换可能仍通过校验；result JSON
也在完整读取后才限制大小。现改为逐级目录 fd + `O_NOFOLLOW` 打开，文件使用
`O_NONBLOCK`，读取前验证 regular-file 类型和大小，读取后核对 device/inode/size/mtime/
ctime、文件名及祖先目录名绑定。result JSON 最多读取 128 KiB + 1 字节，evidence 最多
读取声明大小 + 1 字节（单文件上限 16 MiB）。同大小改写、文件或目录替换、超限均拒绝。

修复 status 非字符串、超大整数分数、非法 Unicode 路径和超长 JSON 整数的异常泄漏；
descriptor 字段必须同时非 null 或同时省略，显式 bind API 不再接受 None root 跳过校验。
合法 099 receipt 的规范化内容、result ID 和 digest 与旧实现比较一致。文件路径范围收紧：
result JSON/evidence 都拒绝祖先 symlink、`..`、超过 4096 UTF-8 字节或 128 个绝对路径
组件；macOS 的 `/tmp`、`/var` 别名也在此列，应使用实际路径。检查是逐文件的有界观察，
不保证多 arm 原子快照，也不证明外部测量真实或评分正确。

新增三文件共 66 项回归；六个 benchmark 文件 **88 passed**。主仓全量 **3919 passed in
221.00s**，JUnit 确认 0 failure/error/skipped；全 src/tests Ruff、compileall、Specify、
diff check 通过。独立审查无 blocker，额外 144 次异常字段探测无未捕获异常。实际 CLI
离线 fixture 已验证成功、文件变化拒绝且不创建 home。051/074/076/078/082 的 601 个
tracked 封存文件相对 `027a235` 保持原样。上轮记录 3854 是统计错误，修复前实际 pytest
collection 为 3853；本轮计数直接来自 pytest/JUnit。

本轮只修复 100，不新增 Feature 101。README、架构、quickstart、验证记录和 Specify 当前
feature 已同步；未运行真实框架、模型、provider、WebAgent、远端服务或 campaign，不产生
效果结论。只在本地 `main` 提交，不 push；真实对照测量与多文件/repository/workflow
candidate 仍需独立设计，尚未完成。

## Feature 100：benchmark comparison evidence binding（已完成）

在 099 comparison result receipt 的 `evidence_sha256` 之上增加可选的
`evidence_path` + `evidence_size` 描述。调用方通过
`benchmark-comparison validate-result ... --evidence-root ROOT` 或
`bind_benchmark_comparison_result_evidence` 时，系统只读检查每个 arm 的相对 POSIX 路径、
非符号链接 regular file、大小、inode/device 稳定性和 SHA-256；缺失描述、路径穿越、符号
链接、文件变化和摘要不匹配均拒绝。未提供 evidence root 时，099 的 digest-only receipt
继续兼容。描述字段进入 result ID，因此路径或大小变化也会产生不同身份。

本功能只绑定操作者提供的本地证据字节，不证明外部框架、模型或 evaluator 的真实性，
不导入分数到 Lunar candidate、score 或 iteration，也不启动任何框架、模型、provider、
远程服务或 campaign。聚焦 benchmark result/comparison/CLI 回归 **11 passed**，全量回归
**3854 passed**，Ruff、compileall 与 diff check 通过；
当前分支 `main`，不 push。下一层仍是多文件/repository/workflow candidate 契约，以及
在新预注册协议下进行真实 SkyDiscover/LLM4AD/WebAgent 对照测量。

## Feature 099：benchmark comparison result envelope（已完成）

新增 `BenchmarkComparisonResult` 与 `ComparisonArmResult`，把未来固定条件测量的每 arm 状态、
计数、耗时、有限分数摘要和 evidence SHA-256 绑定到 098 comparison plan。严格 canonical JSON、
重复键/非有限值/越界字段拒绝，result ID 由 plan comparison ID 与 arm 摘要稳定派生；admission
要求每个计划 arm 恰好出现一次。该层只保存测量证据，不写入 Lunar candidate、score 或 iteration，
新增静态 `benchmark-comparison validate-result` 命令，在普通配置初始化前复用 097 plan/input
pin admission 并绑定 result arms，只输出 ID 与摘要。该层不运行任何框架、模型、evaluator、
provider 或远程服务。聚焦回归 **18 passed**；详见
`specs/099-benchmark-comparison-result/validation.md`。

## Feature 098：固定条件 benchmark comparison plan（已完成）

已开始在 097 task envelope 之上冻结多 arm comparison plan：所有 arm 必须共享 task comparison
digest、contract、model、exact evaluator 与物理预算；framework 名称、score、generation/run ID
不进入比较身份。计划只做严格解析和只读 admission，不运行 SkyDiscover、LLM4AD、Lunar、模型、
evaluator、scheduler 或 Store。098 模块与 097 admission 已完成，聚焦回归 **82 passed**；本轮
没有运行真实 benchmark 或产生效果结论。详见 `specs/098-benchmark-comparison-plan/validation.md`。

## Feature 097：benchmark/task envelope（已完成）

已完成面向 SkyDiscover/LLM4AD 的离线 `lunar-benchmark-task-v1` task envelope：严格规范化
JSON、benchmark/task/contract/input/model/evaluator/budget 身份、稳定 envelope/comparison digest，
以及只读输入字节和 caller pin admission。新增静态 `benchmark-task validate` CLI，在普通配置
初始化前分派，不启动框架、模型、evaluator、scheduler 或远端服务。聚焦测试 **79 passed**，
全量回归 **3842 passed**；本轮不运行真实 benchmark 或生成效果结论。详见
`specs/097-benchmark-task-envelope/validation.md`。

## Feature 096：外部 producer CLI 热启动

已打通用户可直接操作的 Shinka → Lunar population 工作流。新增
`export-shinka-result RESULTS_ROOT --output NEW_ROOT --contract FILE --producer-fingerprint SHA`，
复用现有静态 SQLite exporter；可按重复 `--program-id` 有序选择，或用互斥的 `--top-k`
（默认一条）。命令在普通配置初始化前分派，输出 exported、候选数量和 envelope 摘要，
不创建 Lunar home/Store，也不启动 producer 或 evaluator。

新增 `evolve --producer-result ROOT --producer-fingerprint SHA [--producer-id NAME]`，
仅供 population 使用，并要求原有 `--evaluator-command` 本地 exact harness。它与
`--seed-manifest` 互斥，也不允许 seed dependency/environment 手工覆盖。新公开 API
`prepare_producer_seed_manifest` 复用原 generic adapter 的 envelope/material/pin 校验，
只在内存构造未 admission 的 SeedManifest。随后由原 controller seed admission 唯一地
执行评测、生成 receipt 和提交候选，避免提前或重复评测。dependency 是 source-bundle
摘要，environment 是原 adapter 的 declared-protocol 协议声明摘要，不认证外部框架的运行环境或依赖。

普通 resume 保留完整 seed/ordinary-candidate 复验；`--detach` 传递原始 producer root、
fingerprint 和可选 name pin，不把临时 manifest 或推导参数伪装为用户输入。已用真实本地
Python fixture 验证 Shinka SQLite 导出、good/bad mixed admission、外部高分不覆盖本地
0.42 分、全 invalid 时不启动搜索、恢复复验与稳定 seed ID，以及 source/pin/evaluator/
envelope 漂移拒绝。没有运行真实 Shinka/OpenEvolve、模型、provider、远端服务或 campaign，
没有新增算法效果或 WebAgent 持平结论。

实现、聚焦测试、独立审查、离线构建和最终全量验证已完成：**3831 passed**。操作说明见
`specs/096-producer-cli-warm-start/quickstart.md`，本轮完成本地提交，不 push。
下一层待办仍是 SkyDiscover/LLM4AD benchmark/task envelope 与独立真实验证；本功能只
处理已有的本地单文件候选，未新增 live runner、网络同步、repository/workflow candidate。

## Feature 095 结项：显式执行证据登记

新增 `attest-materialization-execution PARENT CHILD --receipt FILE`。它用于 090 launch intent
已存在、候选留下原始 `execution.json`、但尚未开始 091 登记的现场。操作者主动提供
canonical schema 1 确认文件，绑定 parent/child/唯一 task、完整 launch digest、candidate/
attempt、execution SHA-256/size/device/inode 和 Store 内唯一 nonce。系统不会从原始执行
文件、诊断或证据包自动生成授权。用白话说：人工确认“只登记这个任务的这一份执行结果”，
不授予重跑候选权限，也不证明执行结果是真实或成功的。

CLI 先解析并冻结同一份最多 16 KiB 的 receipt，再复制 093 有界 DB/WAL 到私有临时目录
预检。校验失败不会初始化源 home/数据库或改写运行证据。校验通过后，在现有 090
生命周期锁内复核 workspace/budget、launch owner、候选和 execution 原始文件，拒绝
临时 execution、指纹漂移、已用/冲突 nonce、以及仅存在于数据库的下游证据。

091 journal 可选嵌入完整 receipt，上限扩为 24 KiB；普通执行 journal 内容保持原状。
`materialization_execution_attested` 与 `materialization_execution_prepared` 在同一个 FULL
SQLite transaction 中登记，通过 receipt/journal SHA-256 和 prepared.attestation_sha256
相互绑定。原执行 artifact 和 commit batch 仍复用 091，不另建表或事后补审计。nonce
在同一 Store 的所有 run 中唯一；相同 receipt 精确重试幂等，另一 nonce 不能替换已有 child 授权。

完整 attested journal 已写、DB 尚未 prepared 时，可以显式重交同一 receipt；普通 resume
仍不能创建 preparation。prepared 后，中断恢复直接校验 journal 中保留的 receipt，不依赖
原确认文件，可继续 091 并通过 092 验证输出、发布和完成终态，全程不重跑候选。
成功/失败的本地候选 fixture 均验证了这条交付链。partial/unattested journal、缺失 bytes
及任何下游 088/089/092 记录仍拒绝，保留现场。093/094 已支持新事件和摘要关联检查，报告
和 bundle 不输出 receipt 正文或 nonce，仍不提供恢复权限。

最终主仓全量 **3788 passed in 224.61s**，新增三文件共 189 项（集成 75、Store 98、
诊断 16），已包含于全量。Ruff、compileall、Specify 与 diff check 通过，601 个封存文件
相对 `027a235` 保持不变；Store、恢复/CLI、诊断和文档独立审查无剩余 blocker。详见
`specs/095-manual-execution-attestation/validation.md`。实现已完成并纳入本轮本地提交。
本轮仅使用离线 fixture/本地测试，没有启动真实
模型、provider、WebAgent、OpenEvolve/ShinkaEvolve、远端服务或 campaign，没有新增算法
效果或 WebAgent 持平结论；不 push。其余边界：人工 statement 不认证外部身份，不证明
进程实际运行，不识别/终止未知存活进程，不保证 exactly-once 或成功交付，协议记录暂无 GC。

更新时间：2026-09-14
当前仓库：`/Users/liminghan/Documents/lunar_agent`  
当前分支：`main`  
远端：`git@github.com:vchive/Lunar-Agent.git`  
提交身份：`vchive <vchive@users.noreply.github.com>`

## Feature 094 结项：materialization 证据包导出

Feature 094 新增 `export-materialization-evidence PARENT CHILD --output FILE`，在普通 CLI
初始化之前读取 093 私有数据库/WAL snapshot，并复用该快照生成五阶段诊断。它只导出固定
schema 1 的诊断 report、event identity/type + payload size/SHA-256、artifact identity/kind
+ size/SHA-256；不导出 workspace、goal、命令、原始 payload、候选/输出字节或日志。报告
仍固定 `recovery_eligibility: not_assessed`，证据包不提供恢复权限或成功证明。

输出必须是显式目标，父目录必须已存在，拒绝目标/临时文件冲突、符号链接和任一 run
workspace 内的路径。最多 256 KiB 的 canonical JSON 通过 O_EXCL 同目录临时文件写出并
fsync，再 no-clobber link 到最终文件，最后同步目录；不会覆盖已有文件，也不写源数据库、
workspace、事件、receipt 或锁。相同稳定现场导出到不同路径的 bytes 相同。busy/unavailable
现场在目标创建前拒绝。

聚焦验证 13 passed in 3.84s；Ruff、compileall、Specify 与 diff check 通过；主仓全量
**3599 passed in 205.44s**。没有启动真实模型、provider、WebAgent、OpenEvolve/ShinkaEvolve、远端服务或
campaign，也没有新增算法效果结论。剩余边界保持：bundle 是脱敏观察清单，不是认证的
外部真实性证明；不解决 raw execution/未完整 prepared 的人工授权缺口，不推断存活进程。

## Feature 093 结项：只读 materialization 诊断

Feature 093 新增 `diagnose-materialization PARENT_RUN_ID EVOLUTION_RUN_ID`，用于查看 090–092
保留的启动、执行登记、delivery plan、输出批次和终态凭据。命令在 CLI `_config()` 之前
分派，不创建 home、数据库、Store、memory 或协议锁，也不调用 runner、promoter、rollback
或任何 recovery/publish API。它把 state.db 和可选未 checkpoint 的 state.db-wal 以 no-follow
有界复制到源目录之外的临时目录，只在副本上开启 SQLite；源内容、目录项和业务记录保持
不变（普通读取造成的 atime 变化不在保证内）。源数据库 rollback journal、WAL/DB 超限、
坏节点、访问失败或复制前后身份变化会返回固定 unavailable 错误，不输出底层异常或保留的
goal/命令/日志内容。

报告 schema 1 分别列出 `launch`、`execution`、`delivery`、`outputs`、`terminal` 五阶段，
给出固定的 absent/present/incomplete/invalid/unavailable 观察状态、文件大小和 SHA-256、
协议事件计数、artifact 计数及固定 issue codes。它会显示 prepared、fragment、legacy、
临时和损坏节点，但不把结构存在称为 committed/successful，也永远输出
`recovery_eligibility: not_assessed`。已有锁只以非阻塞共享方式打开；竞争返回 busy，不创建
缺失锁。诊断生成报告的退出码与 materialization 成败无关：observed/attention_required 为
0，busy/unavailable 为 2。报告只提供下一步保留证据并使用正常 resume 的固定提示。

离线验证：snapshot 与诊断聚焦测试 **136 passed in 20.55s**（snapshot 57、报告/CLI 79）；
覆盖 checkpoint/WAL、完整/中断/legacy/碎片、坏节点、敏感信息、锁竞争、缺失 home/workspace、
并发变化、SQLite 与文件边界及源快照保持。Ruff、compileall、Specify prerequisites 和
`git diff --check` 通过；主仓全量复测 **3586 passed in 201.05s**。
没有启动真实模型、provider、WebAgent、OpenEvolve/ShinkaEvolve、远端服务或 campaign，也没有
新增算法效果或 WebAgent 持平结论。

剩余边界：诊断是有界观察清单，不是恢复校验器、授权或成功证明；不重建记录、不验证所有
候选/输入/输出字节、不识别存活进程，也不认证外部 writer。数据库或文件系统在检查中持续变化
时可能返回 unavailable，需要操作稳定后重试。临时诊断副本不会成为运行证据，记录仍无 GC。

## Feature 092 结项：执行后的交付恢复

Feature 092 接通了完整 091 执行登记之后的输出验证、发布和终态完成。resume 在完整
090/091 凭据存在且没有下游发布证据时，可以重新独立验证保留的原 attempt，准备 delivery
plan 并继续交付，全程不调用候选 runner。新模块 `materialization_delivery.py` 在
`evolution/materialization/.delivery-publication/` 保存最多 64 KiB 的 canonical plan，
绑定 launch/execution digest、原 result 身份、execution projection、validation 和有序
输出 path/format/fields/required/size/SHA-256。原输出文件、plan 和目录先同步，再用 FULL
SQLite transaction 登记唯一 child task 的 `materialization_delivery_prepared` 事件。
没有增加 artifact row、schema migration 或输出副本；artifact ID 和 owner 仍由 088
在 parent lock 内选择和核验，保留其他 parent task 的合法复用记录。

恢复先重新核验原始 execution、attempt validation 和计划内输出字节，再在 parent lock
内比较 088 journal metadata。不存在 batch 才可调用原 promoter；已 committed 的 batch
直接复用精确 projection，不重新发布。确认 rolled_back 时生成 outputs=[]、
`error="output_publication_rolled_back"` 的明确失败终态。已准备/已提交的 089 终态优先
按原协议恢复，callback 在任何终态写入前只读检查输出状态。089 完整后写最多 4 KiB 的
delivery completion；final/temp 任一存在时，缺失 terminal rows 都不能自动重建。终态
完整而仅缺 delivery completion 可以补完。092 FS/DB 证据也会阻止 091 重建已删执行 batch。

现代执行完整但缺 plan 时，不会先运行可写的旧 088 recovery：没有精确终态授权的下游
残片在 rollback 或新 plan 写入之前被拒绝。已有 exact prepared 089 仍保留历史恢复能力，
先只读核验输出再完成原结果；完整旧 marker 可回放，不强制迁移。没有现代 091 的更早
attempt 继续遵循原 088 恢复规则。独立审查发现并修正了原先先回滚再拒绝的排序缺陷，
补充零写拒绝与旧 089 恢复两个回归，两路终审均无剩余 blocker。

最终离线验证：092 quickstart 七文件 532 项（91.29 秒）；新增三文件共 249 项，包含
controller/FS 94 项、真实双进程 1 项和 Store 154 项，已包含于聚焦与全量；联合 Store
434 项（2.57 秒，与聚焦有重叠）；主仓全量 3450 项（173.17 秒）。Ruff、compileall、
Specify prerequisites 和 `git diff --check` 通过。051/074/076/078/082 共 601 个 tracked
封存文件相对 `6d6ad49` 无 diff，历史验证数字保持。验证记录见
`specs/092-recoverable-materialization-delivery/validation.md`；README 与 architecture 已同步。
本轮没有启动真实模型、provider、WebAgent、真实 OpenEvolve/ShinkaEvolve、远端服务或
campaign，没有新增算法效果或 WebAgent 持平结论。

剩余边界：raw execution bytes、未完整准备的 execution/delivery plan，以及 088/089
缺少精确 preparation 的残片仍需诊断；缺失 candidate、execution 或 attempt output bytes
不能重建。088 完整 journal 发布前的中断边界及整批 rollback 不重试保持。协议只保留
090 的至多一次 runner 授权进入，不保证 exactly-once 或成功交付，不识别/终止未知存活
进程。各 attempt 记录有界但尚无 GC；协调删除全部协议证据没有外部真实性保护，088 的
文件系统前缀可见性边界保持。通用 runner 和普通演化候选路径未修改。后续应优先考虑
保留现场的诊断/人工恢复入口及记录保留策略，再决定是否扩展未准备完成的自动恢复授权。

## Feature 091 结项：可恢复的执行证据登记

Feature 091 将最终 materialization 的 execution artifact 和事件改为可恢复的原子登记。
新模块 `materialization_execution.py` 只在 final runner 正常返回之后，核对返回的
`CandidateExecution`、原始 canonical `execution.json` 和 090 launch intent。先同步原始
执行文件及目录链，再写 `evolution/materialization/.execution-publication/journal.json`
并同步，之后以 FULL SQLite transaction 保存确定 ID 的 prepared 凭据。4 KiB journal
绑定 parent/child/唯一 task、launch intent digest、execution path/digest/size/inode 和
确定 artifact ID，不复制或重写原始 execution bytes。

单个 FULL transaction 登记 execution artifact、artifact_recorded、原有形状的
`evolved_candidate_executed` 和 `materialization_execution_committed`，之后保存 durable
completion receipt。commit 抛异常必须重新查询完整快照；无法确认时保留现场，不能转成
伪造的失败终态。prepare 和 commit 都在同一 SQLite snapshot 验证 090 intent、owner、
整个 batch 和 artifact budget。既有 partial、duplicate 或 owner/content 漂移均拒绝。

resume 复用 090 全生命周期锁，在 090 execution gate 和 088/089 任何恢复写入之前检查
091。只有精确 FS journal + DB prepared、execution batch 完全不存在、没有 completion
final/temp、也没有任何对应下游 output/terminal 凭据时，才允许续完登记。完整 committed
batch 可以补缺失的 completion；保留完成凭据或下游凭据时删除执行记录不能触发重建。
现代 journal 丢失而 reserved DB 证据还在时禁止降级；旧完整结果没有 091 证据时保持只读。
终态验证也会检查现代执行登记完整性。没有 089 terminal preparation 时，即使 execution
登记已恢复，controller 仍保留原有缺 marker 错误，不调用 runner、输出发布或新终态生成。

最终离线验证：091 quickstart 七文件 359 项（64.02 秒），执行恢复与双进程两文件 98 项
（26.19 秒），联合 Store 280 项（1.86 秒，含新 execution Store 87 项；聚焦集有重叠），
主仓全量 3201 项（136.98 秒）；Ruff、compileall、Specify prerequisites 和
`git diff --check` 通过。051/074/076/078/082 共 601 个 tracked 封存文件相对 `2e3cd95`
无 diff。两路独立终审发现的 child output artifact 被删、仅剩事件时的下游识别遗漏已修复，
补充 absent/prepared 两个回归并重新完成全量验证，最终无剩余 blocker。详情见
`specs/091-recoverable-materialization-execution/validation.md`。本轮没有启动真实模型、
provider、WebAgent、真实 OpenEvolve/ShinkaEvolve、远端服务或 campaign，也没有新增效果
或 WebAgent 持平结论。

剩余边界：execution.json 已存在但还没有完整 FS/DB prepared 时仍不自动补登记；缺失的
原始 execution bytes 不能重建。execution 登记之后如何继续输出验证、发布并准备终态，
以及 output commit 到 terminal preparation 之间的恢复，仍需下一轮协议。090 的至多一次
runner 授权约束保持，不是 exactly-once 或保证最终完成；不推断/终止崩溃后未知进程。
通用 runner 和普通演化候选路径未修改。journal/completion 不做 GC，协调删除所有完成、
下游与 DB commit 凭据缺少外部真实性承诺；088 的文件系统前缀可见性边界保持。

## Feature 090 结项：候选启动意图持久化

Feature 090 为最终候选交付补齐启动前的 durable intent，防止 controller 在 `Popen` 后、
execution evidence 落盘前中断时，resume 把已可能执行的 attempt 当作空 staging 清理并重跑。
新的 `materialization_launch.py` 在 child 的 `evolution/.materialization.lock` 使用非阻塞
flock，覆盖恢复、检查、清理、运行和 088/089 发布的完整 lifecycle。请求的 parent/child、
contract 和 candidate 身份在拿锁前后各验证一次；并发调用立即返回
`materialization_already_running`，之后可复用已完成结果。

通过输入准备、Python eligibility 和 runner 构造后，先同步候选副本及目录链，再以临时
文件 fsync → no-clobber link → 目录链 fsync 写出
`evolution/materialization/launch-intent.json`，最后以 FULL-synchronous SQLite transaction
登记确定 ID 的 child `materialization_launch_intended` 事件。最多 8 KiB 的 canonical intent
绑定 parent/child/task、contract、strategy、candidate ID/path/digest、attempt、runner
fingerprint 和实际 timeout；事件绑定固定路径及 exact digest/size，不新增 artifact row
或迁移。只有本次首次准备且确认完整的调用才能进入 runner 一次，Store 幂等登记或读取
既有 intent 都不授予重跑权限。

intent 临时/最终文件、SQLite 残片或内容漂移均保留现场并阻止 cleanup/relaunch。有 intent
时，在任何 088/089 恢复写入前必须验证真实 execution 文件及独立 artifact/event。完整证据
仍允许 088 验证和安全 rollback，以及 089 prepared terminal 续发；不能补造 execution
记录或从输出推断终态。runner 进入后抛普通异常、没有返回执行结果时固定报状态不确定，
不会伪装成执行前失败。真正的输入/语言检查失败、无 intent 的安全 staging、source-only
contract 和历史完整缓存保持原有语义；缓存请求改变 timeout 也不要求重跑。

最终离线验证：090 quickstart 七文件 252 项（34.47 秒），新增持久化故障文件 10 项
（1.84 秒，与 quickstart 有重叠），主仓全量 3016 项（102.26 秒）；Ruff、compileall、
Specify prerequisites 和 `git diff --check` 通过。051/074/076/078/082 共 601 个 tracked
封存文件相对 `a28411a` 无 diff，Store 与 FS/controller 两路独立终审无剩余 blocker。
详情见 `specs/090-durable-materialization-launch/validation.md`。新增测试全部使用离线 fixture，
没有启动真实模型、provider、WebAgent、真实 OpenEvolve/ShinkaEvolve、远端服务或 campaign，
没有新的算法效果或 WebAgent 持平结论。

剩余边界：intent 只证明授权，不证明 `Popen` 发生。intent 后、runner 前中断可能零执行，
同样禁止自动重试；保证是协议内至多一次 runner 授权进入，不是 exactly-once 或自动完成。
controller 崩溃后候选进程可能仍存活，resume 不猜测 PID 或终止未知进程。执行文件与
execution artifact/event 的恢复登记，以及 output commit 到 terminal preparation 之间
的恢复仍未实现；后续应优先制定 execution evidence reconciliation 协议。通用
`CommandCandidateRunner` 和普通演化候选路径未修改。intent 和旧 publication 记录暂不 GC，
协调删除全部 FS/DB intent 没有外部真实性保护，仍可能与从未授权的旧记录无法区分。

## Feature 089 结项：可恢复的最终结果登记

Feature 089 处理了“最终 result marker 已写出，但 artifact/event 尚未完整登记”的恢复缺口。
新的 `materialization_publication.py` 在 child 的
`evolution/materialization/.terminal-publication/` 保存完整 canonical `result.blob`、journal
及 completion receipt；`result.json` 和父 `evolved_candidate_materialized` 事件仍保持原有
schema 1 形状。controller 在 Feature 088 输出恢复之后、旧 marker/执行检查之前尝试终态恢复，
并复用已有 contract、candidate、execution、output validator；不重新运行候选或发布输出。

顺序是 staging/journal fsync → SQLite prepared receipt → no-clobber marker 与目录 fsync
→ FULL-synchronous SQLite 原子 terminal batch → durable completion receipt。terminal batch
只新增结果 artifact、对应 artifact_recorded、原有父终态事件和 child committed
acknowledgement；execution artifact/event 必须早已完整，恢复不能补造。prepared receipt
绑定 parent/child/task、journal digest、结果 digest/size 和确定 artifact ID。只有存在精确
prepared 凭据、没有任何 completion 凭据、且 terminal batch 完全不存在时，才允许续完登记。

数据库提交异常须重新查询完整快照，不能把待提交的成功结果改写为失败。partial、unknown、
身份/内容漂移、现代 journal 丢失都保留现场并拒绝交付。`completed.json` 及其临时文件都表明
数据库已经提交；它们存在时缺失任何 terminal 证据都不能自动重建。若完整数据库和 marker
仍在，仅 completion receipt 缺失可以补完；已有 completed 文件也会补 fsync，以覆盖 link
后、目录同步前的进程中断。旧结果只有在不存在任何 089 协议证据时，才能按原有严格只读
规则复用。child 级文件锁只串行化终态发布与恢复。

最终离线验证：089 聚焦四文件 251 项（24.97 秒），终态恢复与双进程测试两文件 51 项
（10.53 秒，和聚焦集有重叠），主仓全量 2903 项（89.67 秒）；Ruff、compileall、Specify
prerequisites、`git diff --check` 通过。051/074/076/078/082 共 601 个 tracked 封存文件无 diff，
Store 与 FS/controller 两路独立终审均无剩余 blocker。所有新增测试都是离线 fixture；没有启动真实模型、
provider、WebAgent、真实 OpenEvolve/ShinkaEvolve、远端服务或 campaign，也没有新的效果或
WebAgent 持平结论。

剩余边界：本协议从 durable terminal preparation 开始提供恢复能力；此前的中断仍保留现场
并要求诊断，包括 `Popen` 到执行证据落盘、执行证据到 ledger/event 完整登记、以及 Feature
088 output commit 到 terminal preparation 之间的窗口。不能声称严格 exactly-once execution
或恢复所有执行后的崩溃。stage/journal/completion 暂不 GC，没有外部真实性承诺；协调删除
所有 completion 凭据及 terminal 数据库记录，仍可能与未提交的 prepared 状态无法区分。
后续应优先为候选启动及执行证据建立 durable intent/reconciliation 协议。

## Feature 088 结项：可恢复的演化输出批量发布

Feature 088 补齐了上一轮记录的多 output 发布边界。父 workspace 的
`.evolved-output-publications/` 保存同盘 staging、严格有界的不可变 journal 和 rollback
acknowledgement。journal 绑定 parent/child/owner、完整输出 projection、原文件是否存在以及
stage 的 device/inode。父级 flock 串行化发布与恢复；所有输出和完整 ledger 通过预检后，
以 no-clobber hardlink 发布新文件，并在一个 FULL-synchronous SQLite 事务中登记全部新增
output artifacts、artifact events、既有 `evolved_outputs_promoted` 和绑定 journal digest
的 `output_publication_committed`。复用的文件和目录同样先 fsync；旧文件和其他父任务的
合法 artifact ID/owner 保持不变。

提交异常必须回查完整一致的数据库快照，不能直接视为未提交。只有确认未提交时才删除
仍匹配 stage inode 和 digest 的本次新增链接，整批预检在任何删除之前完成；rollback
中断后会补同步已删除路径的目录。commit/rollback 不可确认、journal/输出/ledger 漂移时保留
现场并拒绝 terminal claim。恢复先于 materialization marker replay，验证 journal owner
与数据库 owner；日志目录丢失但 SQLite acknowledgement 仍在时禁止降级。重复发布请求
改变 bytes、owner 或输出集合也会拒绝。路径大小写/Unicode 别名、文件/目录前缀冲突和
跨 volume 输出会在发布前拒绝。

最终离线验证：088 聚焦四文件 196 项（15.30 秒），主仓全量 2787 项（83.45 秒）；Ruff、
compileall、Specify prerequisites、`git diff --check` 均通过。051/074/076/078/082 共 601 个
tracked 封存文件无 diff，独立终审无剩余 blocker。离线测试覆盖第二文件/第二 artifact/事件失败、commit
后异常、不可查询的数据库、真实进程 `os._exit`、rollback 中断、双进程争锁、复用输出、
日志丢失和完整性漂移。没有启动真实模型、provider、WebAgent、OpenEvolve/ShinkaEvolve、
远端服务或 campaign，也没有新增效果提升或 WebAgent 持平结论。

剩余边界：逻辑原子性交付以 SQLite batch 为准，任意文件系统读者在发布期间或 crash 后
恢复前仍可看到部分路径。stage/journal 暂不 GC；完整 journal 发布前的中断保留现场并要求
诊断，同一 evolution identity 的已回滚 batch 不会重新发布。恢复不会执行候选，也不会补造
缺失的 terminal marker。`Popen` 到 durable execution evidence 的窗口，以及 terminal
marker 与 materialization ledger/event 分开持久化的缺口在 088 结项时仍未覆盖；后者已由
上面的 Feature 089 在明确 prepared 凭据之后实现恢复。flock 只协调本模块的
发布者，不对其他同用户进程提供文件真实性保证。后续开发应分别为这两个窗口制定恢复协议，
不要将本轮离线工程验证解释为新的算法效果测量。

## Feature 084/085 结项：verified seed 与 population-first

Feature 084 与 Feature 085 已于 2026-09-14 完成实现、离线验证和独立终审。所有新演化任务
只接受 `population` 或显式 `openevolve`；默认 contract、`solve --evolve`、standalone
`evolve` 与 benchmark 均使用 `population`。历史 `loop` contract/archive/result 仍可只读，
但新建、controller resume、CLI answer 以及 `LoopStrategy.run()`/`resume()` 都会在首次 mutation
前固定拒绝并给出 `loop_strategy_retired`。显式 OpenEvolve 只提供候选 material，必须经过 Feature 084
的本地 exact evaluator、verified seed receipt 和 canonical commit，外部分数不进入 Lunar
score、rank 或最终交付权威。

恢复与 writer 边界已补齐：root/stage/backup 会在任何创建、替换、清理或 callback 前只读
预检；state/config/archive/result/outcomes 严格拒绝重复 JSON key、非有限数值、历史 loop、
unknown、mixed 与 cross-strategy operational evidence。materialization 将 state/archive/result、
artifact ledger、candidate digest、execution artifact/event、parent output、promotion event 与
terminal marker 绑定；marker 缺失而 `execution.json` 或 `.execution.json.tmp` 存在、异常或不可
检查时保留现场并拒绝重跑。

最终离线验证：Feature 084 聚焦 507 项（10.91 秒），Feature 085 聚焦 583 项（27.55 秒），
主仓全量 2673 项（78.26 秒）；Ruff、compileall、两个 Specify prerequisites、
`git diff --check` 均通过。051/074/076/078/082 共 601 个 tracked 封存文件相对当前 HEAD 无
diff，独立终审无 P0/P1/P2 blocker。本次没有启动模型、provider、WebAgent、真实
OpenEvolve/ShinkaEvolve、远端服务、company evaluator 或 campaign，也没有产生新的效果提升、
有效解率提升或 WebAgent 持平结论。

084/085 结项时仍保留两个系统边界。Feature 036 的多 output 发布没有跨文件系统与 SQLite ledger 的整体事务；
第二个 output artifact 失败时可能残留前面已发布的文件和 ledger row。完整修复需要 Store 批量
事务、同盘 staging、commit/rollback journal 与 crash recovery；此项已由上面的 Feature 088
实现可恢复批量发布。另一个边界是 subprocess
`Popen` 成功到 `.execution.json.tmp` durable publication 之间的硬崩溃窗口；在没有 durable
pre-launch protocol 或独立事务的情况下，现有证据不能判定候选是否已经执行，因此不能声称
严格 exactly-once。

## 最新续作：Feature 087 ordinary candidate integrity

Feature 087 已为普通 `population` 候选补齐离线、可恢复的完整性边界。每个新候选都以
canonical `CandidateReceipt` 绑定 source、lineage、规范化 evaluator report、contract、
evaluator、dependency、environment、runner 和 generator identity；可选 `execution.json`
也以精确 digest 绑定。archive line 保存 compact integrity projection，state 保存统一
authority 和 archive digest；credential-shaped `evaluator_kind` 会在 config/context、
authority 和 receipt 层全部拒绝。source 与 execution evidence 的 no-follow descriptor 从评测前
持有到完整 publication 结束，并在 receipt、record、目录 fsync、archive append/fsync
边界重复核对；evaluator 返回的嵌套 report 会立即深复制，避免回调返回后再被修改。

普通候选 publication 现在按 source → receipt → record → archive 的顺序落盘，archive 与
outcome append 在写前检查总大小不会超过 reader 上限。append 或 fsync 失败会回滚到旧长度，
再次 fsync，并在截断及目录 fsync 后确认当前路径仍指向 held inode 和旧 size；若 publication
与 rollback 都无法确认，则固定抛出
`ordinary_candidate_archive_publication_unknown`，保留 orphan source/record/receipt 供诊断，
但不让其进入 canonical archive、resume population 或 controller index。evaluator/worker
失败仍不生成 receipt。`CommandCandidateRunner` 在正常 leader 退出后也会清理同 PGID
descendants。

resume 在 generator/evaluator 调用前校验 config、authority、source、execution、receipt、
record、archive、outcome、state、lineage、island 与 active population；新版 integrity state
缺少 config 也会 fail closed；非法 parent 结构即使 receipt/record/archive 的完整绑定被同步
重算仍会拒绝。现代 ordinary-integrity state 的 `active_ids`、`best_candidate_id`、`rng_seed`、
`last_migration_iteration` 和 `stagnation` 会从已验证 archive 按 seed/iteration 顺序重放
rank/trim/migrate/best/stagnation 规则后重建；替换、迁移/停滞水位漂移、bool/float 数值类型绕过
及与 projection 冲突的 status 均以 `population state projection mismatch` fail closed。marker
仍可见时，需要 outcome binding 的现代 checkpoint 不能通过同时删除整组字段和 journal 降级为
legacy；不完整 pending batch 和空 seed population 保留原有更具体错误的优先级。ordinary
marker 一旦由 pending state 建立，后续 state 会单调保留；seeded 首批 offspring 全失败且没有
ordinary record
时也不能丢 marker，带 modern marker + `seed_admission` 的 state 必须保留 outcome binding，
因此 marker 仍可见时删除 outcome 整组会 fail closed。若协调删除 marker 三字段、完整
outcome/failed binding 和 journal，seed-only archive 与真实 Feature 084 pre-ordinary checkpoint
不可区分，不在 Feature 087 的无外部承诺边界内。旧普通 archive 可以只读，
但不能作为 active population 静默恢复。完整 pending batch 可以在不重放 callback 的情况下
finalize；不完整 batch fail closed。controller 只索引 canonical sidecars；失败路径只允许
state digest 已绑定且完整验证的普通 archive 前缀，并跳过未提交 seed sidecar，避免伪 seed
证据进入 ledger；generic indexing hook 永不直接发布 population seed，seed evidence 仍只走
独立 commit gate。同一 `(path, kind)` 的既有 ledger rows 若 digest 或 size 冲突也会 fail
closed，不会用首条记录掩盖冲突。

最终离线验证：087 聚焦三文件 212 项（3.69 秒），主仓全量 2408 项（65.02 秒）；Ruff、
compileall、Specify prerequisites、`git diff --check` 均通过，074/076/078/082 共 595 个 Git
封存文件无 diff，两路独立终审无剩余实现或行为 blocker。没有启动模型、
provider、WebAgent、OpenEvolve/ShinkaEvolve、远端服务或 campaign，也没有新的效果、有效解率
或 WebAgent 持平声明。保留的系统边界包括：同用户进程
仍可能在最后一次 publication 校验后再次改写路径；resume 会拒绝没有同步重算或替换全部
hash-bound artifacts 的 drift，但 receipt 没有外部签名/HMAC，不能对能一致改写
source/receipt/record/archive/state 的同用户进程提供真实性保证。父路径组件核验与完整路径
`open()` 之间仍有系统级 TOCTOU；controller 异常前缀搜索是低频 O(n²) 路径；首次 state 尚未
写入时恢复已发布初始候选会固定报
`ordinary_candidate_integrity_state_missing`。纯 seed、尚未开始 ordinary transaction 的
checkpoint 仍属于 Feature 084；state 对任意字段没有独立外部承诺，空初始化
`candidate_failed` 的 running/failed status 与 error 若被协调改写，不能只靠该 state 判别。
projection replay 依赖当前 rank/trim/migrate/family 规则，后续算法变化必须升级 integrity
schema 或显式迁移。

## 最新续作：Feature 086 remote material handoff

Feature 086 已在当前工作树完成离线实现并完成独立审查：新增
`src/famou/remote_material_handoff.py`，把已由调用方取得并可选 reconcile 的
`RemoteExperimentState(status="completed")` 转换为通用 `ProducerResultEnvelope`，再通过
对象级 `admit_producer_envelope` 进入既有本地 exact evaluator、receipt 和 verified-seed
admission。只有 pinned producer ID/fingerprint、非空 `candidate_source` references、有效
bounded budget 和本地 regular-file/大小/UTF-8/path-confinement/SHA-256 校验全部通过才会调用
evaluator；remote completion、timestamp、attempt、原始 state ID 和 score-like evidence 只保留
摘要。generic-safe experiment ID 可以作为经过校验的 opaque `producer_run_id` 标签保留，但
不能成为 Lunar score 或 candidate identity，也不能直接生成 Lunar rank、archive 或 population
状态。指定的 staging root 必须与 material root 严格 disjoint（包括解析后的文件系统别名），
避免 admission 在同步目录内创建临时文件。该 bridge 不执行 backend、网络、
subprocess、scheduler、模型或 campaign。

新增 remote bridge 生命周期、伪造 DTO、material/staging 路径别名和固定错误边界测试，并补充
Shinka SQLite → exporter → generic producer admission 端到端离线 fixture：高 producer 分数
不会覆盖本地 evaluator 的 0.42 分，lineage 保留，无效候选进入 rejected subset，原始
score/prose 不进入 canonical metadata。当前工作树全量收集并通过 2262 项（基线 2210，另含此前
Shinka/producer 变更及本轮测试）；最终数字以本轮全量 pytest 输出为准。

## 演化生态融合与 OpenEvolve verified producer

本轮已把“Lunar 融合外部演化项目”的边界落实到离线实现。OpenEvolve、未来的
ShinkaEvolve 及远端 famou-v2/WebAgent 控制面只提供候选 material；Lunar 继续持有
algorithm contract、本地 exact evaluator、receipt、canonical archive、resume、rank 和最终
交付权威。OpenEvolve 是 AlphaEvolve 风格的第三方 Apache-2.0 开源实现，不是 Google
DeepMind 官方源码；其他公开项目及分层接法记录在
`docs/evolution-ecosystem-fusion-roadmap-20260911.md`。

新增 `src/famou/seed_handoff.py`、`remote_evolution.py` 和 `openevolve_handoff.py`。外部 seed
的 evidence 与 record metadata 在 canonical persistence 前都规范化为固定
`{present, score_present, payload_sha256}` 摘要，不保存原始外部分数、payload 或 prose；
seed identity 绑定 evaluator kind 与 fingerprint，receipt 只接受 report schema `1`。
manifest/source/symlink/大小/编码/控制字符/lone-surrogate/深层 JSON/material-ref 边界均使用
固定错误码。远端 backend 目前只有 bounded、score-free 的
`submit/status/sync/continue_experiment/cancel` DTO/protocol 和 unknown reconciliation，没有
网络 transport，也不会由默认路径实例化。

`PopulationStrategy` 已支持 verified seed 的私有全批裁决、原子 commit、稳定 `seed-*` ID、
generation/iteration 0、确定性 island、receipt/provenance/handoff 校验及 fresh resume
revalidation。offspring 使用五类 durable outcome：`evaluated`、`candidate_failed`、
`evaluator_timeout`、`worker_unknown`、`run_failed`；journal、SHA watermark、archive baseline
和 candidate 双向绑定已落盘，failed-only batch 不推进正式 iteration，完整 outcome 可在
resume 时只 finalize 而不重放。

`OpenEvolveStrategy` 在 mode-0700 系统临时目录运行显式 producer，传入 bounded
contract/budget/config，stdout/stderr 直接丢弃，timeout/cancel 清理进程组。producer 结果先走
同一 seed handoff 和本地 exact evaluator，再原子发布一个 `strategy=openevolve`、
`iteration=1`、`island_id=null` 的稳定 `seed-*` candidate。completed resume 不重跑 producer，
而是从 canonical source/sidecar 重建 admission，重新调用本地 evaluator 并核对
source/receipt/provenance/config。外部 evaluation 无论分数多高都不会进入 Lunar 排名；本地
evaluator 异常、invalid 或 `None` 时为 0 candidate。

controller 的 seed evidence 事件分为 deterministic `seed_admission_adjudicated` 和实际
state/commit-marker 匹配后的 `seed_admission_committed`，并登记 marker、record、receipt 和
offspring outcome artifacts。terminal resume 会先核对 SQLite run 与 canonical state 的
status、strategy、contract、config、seed manifest/marker；缺 state 的失败或取消任务不能被
新 manifest 复活，避免 run/state split-brain。孤立 seed identity 参数在 claim 前拒绝。

新增 `src/famou/producer_handoff.py`，提供 transport-free 的
`ProducerResultEnvelope`/`ProducerMaterial` DTO、对象入口 `admit_producer_envelope` 和文件
入口 `admit_producer_result`。OpenEvolve、
ShinkaEvolve 或其他 runner 只需把已落盘的候选 material `{path,size,sha256}`、producer
identity、lineage、预算和 terminal status 导出到同一 envelope；Lunar 以一个全批
`SeedManifest` 绑定 source-only bundle digest，统一做 exact-harness admission 和确定性
island 分配。外部 metrics/evidence 只保留 `{present, score_present, payload_sha256}`，不
进入 Lunar score/rank。多候选 mixed batch、路径/size/digest/symlink/FIFO、未知字段/status、
credential/deep-evidence、空 terminal envelope 和 local invalid evaluation 均有离线测试；
没有启动真实 ShinkaEvolve 或任何远端 transport。Shinka 后续只需显式导出 `best/main.*`
及 parent lineage，不能把其 generation/SQLite ID 映射成 Lunar iteration。

当前新增的 `src/famou/shinka_handoff.py` 是上述边界的离线 exporter：它只读打开
`programs.sqlite`（缺失时才使用 `evolution_db.sqlite`）的静态、无 WAL/SHM/rollback-journal
sidecar 快照，支持显式有序 `program_ids`（此时省略 `top_k`），并把省略 ID 时的 `top_k`
保留为按 `correct=1` 与 producer score 排序的 convenience 选择，省略 `top_k` 默认取一条。
候选优先来自
`gen_<generation>/main.<ext>`，仅在该文件缺失时回退到 `best/main.<ext>`，且必须与 SQLite
中的 `code` 字节完全一致。导出目标必须是不存在的新 leaf，已有 parent 必须是无任意 symlink
组件的目录；目录提交后的 parent fsync 不确定时会保留已发布树并返回固定 commit-unknown。
导出后直接调用 `admit_producer_result`；`combined_score`、
`correct`、metrics 和 generation/SQLite 元数据都只归一化为外部 evidence，parent IDs 仅作
有界 lineage，不参与 Lunar exact evaluator、score、rank 或最终交付权威。该 exporter 不启动
Shinka、模型、网络、Slurm 或远端服务。

初始化 evaluator 异常现在使用固定 `run_failed`、`evaluator_timeout`、`worker_unknown`
代码；候选 source tree 在评测异常时清理，不再生成带异常正文的 synthetic invalid report，
fresh failure 保持 iteration 0 并在无 active candidate 时 fail closed，terminal resume 不会
重放 generator/evaluator。generator-only 初始失败仍保留旧的 offspring retry 兼容语义。普通
offspring/candidate 尚未拥有与 imported seed 等价的 contract/evaluator/dependency/environment
四类完整 fingerprint/receipt，后续应另立 Feature，避免混改现有 archive schema。

最终离线验证：remote lifecycle/producer/Shinka focused 130 项；主仓全量 2262 项（基线
2210 项加本轮及此前新增测试）；全 `src/famou`/`tests` Ruff、compileall、Specify
prerequisites、`git diff --check` 均通过。074/076/078/082 的 595 个 Git 封存文件无 diff。
没有启动模型、真实 OpenEvolve/ShinkaEvolve、WebAgent、provider、公司平台、远端 backend
或 campaign，也没有复写任何历史 measurement。

Feature 084/085 后续已完成实现、任务核验和独立终审，结项状态与最终验证见本文件顶部。
此处所述普通 offspring/candidate 完整 receipt/fingerprint schema 后来由 Feature 087 完成，
remote material bridge 由 Feature 086 完成。仍保留的后续项包括 ShinkaEvolve exporter 的
更广泛真实 runner/benchmark 验证；SkyDiscover/LLM4AD 先接 benchmark/task envelope，
仓库型或 workflow 型候选另开冻结 Feature。离线互操作本身不构成有效解率提升证据。

## 0. 历史续作起点：Feature 084

已找到并离线审查本地 `famou-v2` 仓库（`/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/famou-v2`）及 WebAgent 2.5 分支。审查结论是：famou-v2 的深度演化通过远端实验控制面运行；其 `initial_programs` 必须经过本地 evaluator enrichment/可行性门槛，有效 rollout 才推进正式 iteration。WebAgent 的 `evolve_create/status/sync/continue/cancel` 是服务委托，不是 Lunar staged Build 的本地 runtime。

Feature 084 当时以草案写入 `specs/084-verified-seed-handoff/`，目标是先实现本地 verified seed adapter、身份/lineage/provenance/evaluator receipt 和恢复校验，再定义显式但暂不联网的 famou-v2 backend protocol；该 Feature 后续已按此边界完成。远端分数只能作为 provenance，必须经 Lunar 本地 exact harness 重验后才可进入 population。084 不启动模型、WebAgent、provider、公司评测、真实 famou-v2 服务或新 campaign，也不改变 074/076/078/082 封存文件。审查证据见 `docs/famou-v2-engine-review-20260911.md`、`docs/webagent-v25-branch-audit-20260911.md` 和 `docs/webagent-v25-evolve-service-audit-20260911.md`。

## 1. 历史状态：Feature 083

083已完成可选主机执行保护，`.specify`当时指向083。新增公开Python接口
`host_execution(report_path)`，普通/深度trial CLI增加`--keep-awake-report PATH`；默认
路径和原生结果不变。macOS进程持有PreventUserIdleSystemSleep断言，派发前同步查询
验收并fsync日志及父目录，结束时查询/释放；单次scope覆盖配置/凭据读取及原trial调用。
日志必须新建且位于workspace及case-source之外，拒绝symlink、覆盖、文件篡改和目录
别名绕过；跨PID拒绝，并发单次状态受锁保护。取消/写入/释放失败均保留原业务异常，
FD关闭结果不确定时不盲目重试旧编号。日志分别记acquisition/release/work状态与墙钟、
monotonic原始采样及有符号区间，不保存凭据、候选、评分或异常文本。

新增163项、相关222项（5.21秒）、独立163项（0.24秒）通过。主仓首次全量发现一项
082测试依赖当前38源码文件的陈旧假设，已改为从082固定Git blobs构造临时副本，保留
缺失HTTP helper拒绝检查；该模块54项root/独立均通过。最终主仓1982项全量通过
（60.95秒），全src/tests Ruff、Specify、diff通过。两个本机native scope正常/异常路径
以及普通os._exit(0)局部退出清理验证通过，证据见083 validation；不泛化为真实睡眠或
所有崩溃模式保证。074/076/078/082各68/105/205/217份Git封存文件未变，未跑旧
live-source审计、WebAgent、provider探测、候选补评或新campaign。

目标仍是GLM-5.2分阶段Master→Build完整交付并通过原生harness。083只解决主机策略
和观察证据，不证明有效解率改善，不阻止合盖/手动/低电睡眠，不改变原有timeout或预算。
后续优先单独定义单次请求时限与有限传输恢复，明确共享期限、物理尝试和未知usage
边界，再以新登记实评验证；不重开082/078旧槽。082维持有效0/2，普通流程历史2/2
只作背景，旧失败分数/完整usage/cost仍null。以下082及更早记录保留为历史。

082已完成终局核验与封存：2026-09-11 14:21:02 +0800两槽均已结束，计划验收/进入Build
各2/2，最终有效解0/2；无checkpoint/续跑/subject完成回执/harness，分数及完整失败
usage/cost均null。钣金subject原生5280.137秒，最后请求open_response/transport_timeout
4036.528秒对期限4036.519秒；邮政subject1324.816秒，最后请求14.901秒对3970.214秒，
属于提前报出的传输超时，不能判定具体provider原因。钣金计划交付文件均缺失；邮政
solve.py及三份output存在，缺摘要和回执，未执行候选补评。详情见082 postrun/results.md。

独立终审与root复验251证据SHA通过；38源码/122冻结/36历史项，以及074/076/078
各68/105/205份Git封存文件保持原样。watcher33500已退出0、保存172快照；进程核验
联合190份证据、10PID/5PGID及可见后代/argv/cwd未见残留，保留时点和脱离后代局限。
T082全部关闭；产品仍固定e36b103，未新增产品改动或开启下一批campaign。不要重试
已失败槽、运行候选补分、改旧manifest或运行旧live-source审计。

本轮系统日志含多次Sleep/Wake；Python/外层wait均使用不计系统休眠的mach_absolute_time，
原生计时不等墙钟，13:56旧ETA已撤回，不能把墙钟差值当deadline失效或精确休眠时长。
下一项优先明确评测主机保持唤醒与时间口径，再设计单次请求预算/有限传输恢复及未知
usage约束。WebAgent固定代码比较已独立复核，见docs/webagent-transport-recovery-review-
20260911.md；不直接照搬SSE重放或TTL计数。目标仍是分阶段真实交付与原生有效解，
普通流程历史2/2继续作为已验证背景。以下为082运行中的历史观察，以上述终局为准。

082进展13:59：墙钟已超过此前估算的13:56工作截止，但slot1仍无原生终止记录，不能
按UTC差值判定monotonic预算耗尽。root只读power投影记录了本轮Sleep33/Wake35/
DarkWake32事件；实际Python monotonic/perf_counter实现为mach_absolute_time，SDK
说明其不累计系统休眠（mach_continuous_time才继续前进）。此前13:56墙钟ETA撤回，
没有精确重建休眠时长，也不能据此确定任何模型传输失败根因。证据见082
postrun/observations/20260911T055914717921Z-host-power-time.json。未保存原始电源日志或
改变主机配置/运行条件；继续等slot1原生终止，T082-05/06仍开放。

以下13:01为邮政终止观测；slot1最新状态以上述13:59说明为准。

082进展13:01独立partial：邮政slot2已原生失败终止（subject1324.816秒、退出2），钣金
slot1仍Build。238项证据SHA通过；邮政合法v4为model/model_failed，typed
transport_timeout，phase=open_response，elapsed14901ms、request_timeout3970214ms，
HTTP/status均null。本次不是共享预算耗尽，不能进一步确定底层或provider原因。
无subject/harness回执、无评分、完整失败usage/cost未知，当前1/2终止而非本批最终0/2。
新审计为082 postrun/observations/20260911T050153627104Z-independent-partial-audit.json
及同时间report.md；root核对报告SHA。slot2进程观察05:03:52 UTC未见已知PID/PGID及
可见后代/slot2 cwd残留，slot1仍活跃，不宣称全批清理。13:15 root逐槽诊断再核验6份
终止证据，确认solve.py及3份output文件存在，缺少_agent_summary.md/receipt.json；
仅文件元数据，未执行候选或补评。详情见同目录20260911T051522240740Z-slot2-terminal-
diagnostic.json。冻结条件未改；T082-05/06继续开放，等slot1终局再作全批终审封存。

后续判读与进程核验方案见082 postrun/terminal-decision-guide.md和process-cleanup-review.md；
它们是运行期只读审查说明，不是本批最终结果，不授权新增尝试或改变原生评分边界。
本地固定WebAgent e24恢复策略已作独立只读比较，18份blob身份及关键source/dist逻辑
复核通过，见docs/webagent-transport-recovery-review-20260911.md。可研究有限传输恢复，
但需单独解决共享期限、物理尝试计数、未知usage预留及回执契约；不能把SSE卡顿重放
当作本次非流式错误的现成修复，不能照搬会受300秒TTL影响的重试计数。没有执行
WebAgent、外部探测、当前槽重试或新产品改动，下一项仍待082终局证据及封存。

以下12:41及12:35为较早观测，当前终止状态以上述13:01记录为准。

082进展12:41：第二份独立只读partial审计通过227项证据SHA，钣金slot1与邮政slot2
均已验收Master计划并进入Build（2/2）。两槽均未续跑、仍started_unresolved，终止0、
subject/harness回执0；分数、完整用量和费用均null，尚无最终有效解结论。新观测为082
postrun/observations/20260911T044152076409Z-independent-partial-audit.json及同时间report.md；
root核对保存JSON/报告SHA与阶段计数。12:35旧观测保持原字节。不改冻结条件、不重试；
继续观察到两槽终止，再作独立终审与进程核验。T082-05/06仍开放。

以下12:35记录是较早的观测，最新阶段状态以上述12:41记录为准。

082进展12:35：独立只读partial审计通过225项证据SHA，邮政slot2的Master计划已验收，
Build进入证据已确认；钣金slot1仍Master。两槽均started_unresolved，终止0、回执0、
harness0，尚无分数或最终有效解结论。观测为082 postrun/observations/
20260911T043548445457Z-independent-partial-audit.json及同时间report.md；root核对保存报告
SHA与计划/Build各1、终止0计数。没有更改运行条件或重试；继续等两槽终止再做最终审计。

082已在登记021b3d0396d3dbe982dd250b5da956bbc7ce469f推送后于2026-09-11 12:28:28 +0800
唯一启动。dispatcher PID/PGID88086；worker88266/88267；subject88272/88273来自可见PPID
链和固定argv角色核验（原生subject-started marker的child PID为null，未伪填）。两槽初始
均master_running、未决，无已验收计划/Build/回执/评分。新HTTP workers已在对应subject
PGID内观测到，身份快照见082 measurement/initial-descendant-processes.json；不保存原始
argv或进程环境。root只读watcher session33500每30秒保存postrun/progress；其marker派生
进程列表不穷尽子进程，最终检查必须纳入独立快照的subject PGID/HTTP helper与cwd关联。
不要再prepare/check-only/dry-run/launch，也不要改已冻src/scripts/tests/inputs/readiness。
当前仅观察082 summarize/postrun audit和元数据；T082-05/06必须等终止、独立终审及封存。

以下是082启动前登记记录，当前运行状态以上述说明为准。

082已完成新测量登记，`.specify`指向082。源固定e36b103，GLM-5.2，钣金/邮政各一新S槽，
Master1200/build2400/reserve120、共享5400秒/200工具/800万tokens，一波并发2、不补位。
232项实现定向、232项独立复核、1819项主仓全量（53.27秒）、73项单独loopback验证通过。
唯一prepare已完成；实际独立preaudit与449项正式guarded dry-run通过，原样报告已镜像。
38源码/122冻结/36历史/23helper与实际shebang解释器、Python/SSL和HTTP helper身份一致。
manifest SHA880761221b0ac2bb11acaffac2dbb8312171ae91adcc6da5ffd06763d2546bdb。
当前尚未launch；登记提交推送后才能唯一启动。T082-01至04完成，05/06待真实终局和封存。
不要再prepare或改已冻src/scripts/tests/inputs/readiness。未作provider探测、WebAgent执行
或公司平台查询；本次测079/080/081合入整体表现，不作纯deadline因果结论，不解释078
旧根因。074/076/078各68/105/205份Git封存文件保持原样。正式失败诊断会绑定原生失败
记录、请求及双副本，只投影v1–v4固定字段，不改变回执/harness/评分或补回完整失败成本。

081已完成有限timeout的绝对HTTP传输截止，`.specify`指向081，T081全部关闭。stdlib
独立exec HTTP worker受父进程统一deadline约束并kill/wait回收；匿名lifeline处理父进程
单PID死亡，worker继承subject PGID。请求/凭据走有界匿名IPC，环境净化；保留代理绕行、
标准TLS行为、None直接urllib及v4/legacy失败分类，不接受迟到成功或失败，不自动重试。
66项HTTP＋7项HTTPS新增测试、464项实现定向、73项独立复核、主仓1687项全量（50.45秒）
通过；Ruff/Specify/diff通过。离线wheel安装到独立venv后，public complete成功加载包内
helper；正常请求成功，0.3秒慢体在0.3041秒被拒绝，全程只有两次loopback请求。
074/076/078各68/105/205份Git封存文件保持原样，没有新增真实评测或provider探测。

当前目标仍是GLM-5.2分阶段Master→Build完成交付并经原生harness验证。下一步需围绕
当前产品准备新的固定测量登记，使用已有WebAgent高分case背景，不重跑WebAgent、
升级模型或重开旧槽。081不能证明078的旧超时根因或有效解改善；078保持有效0/2，
旧分数与完整失败usage/cost未知。纯模型解析仍在父进程，不宣称整个complete硬实时
返回或服务端停止计费；当前验证是macOS证据，Linux尚未实跑。

以下为080及此前历史状态；080当时提出的HTTP截止改造已在081完成。

080已完成最后失败请求的阶段与耗时证据，当时`.specify`指向080，T080全部关闭。产品只改
runtime/subject_diagnostics；v4新增request_observation固定phase、elapsed_ms及实际
传入的request_timeout_ms，保留v1/v2/v3与原异常链/成功解析/请求参数/账本/评分边界。
坏时钟或无效时序安全回退v3，不跨请求或异常节点复用证据。76新测试、391实现定向、
238独立定向和主仓1614全量（39.79秒）通过，独立审查/Ruff/Specify/diff通过。
078/076/074各205/105/68份Git封存文件未变。本轮无新增真实评测、provider探测或重试；
078有效解仍0/2，不能由080补回它的未知时序或完整失败usage/cost。
未来失败可区分请求打开、响应体读取、解析校验与HTTP错误正文处理；它仅是终局诊断，
不覆盖成功请求历史或外层强杀，不能断言具体网络/provider原因。root独立本机fixture
确认timeout=0.15秒的分段200响应在0.3100秒仍成功：urllib限制单次socket等待，不保证
整个HTTP请求deadline。下一项应单独定义并验证绝对请求截止行为；需要真实验证时另作
固定登记，不改旧槽。该问题不能回填为078两次超时的根因。

078已在`a80f9b8`封存推送后，合入079安全模型失败诊断（isolated `b2ed0e9`，merge
`27eb0cc`）。`.specify`现指向079，T078/T079全部关闭。主仓1538项全量测试（40.13秒）、
全src/tests Ruff、Specify/diff通过；独立集成复核确认37源码/74测试/31Specify/3规范
与已审版本一致，078新增两份主仓测试保留，078/076/074各205/105/68份Git封存文件未变。
079仅为自有typed模型失败补充v3固定reason/response_status，保留原失败分类、v1/v2、
成功解析、预算、回执和原生评分权威；无重试、补跑或新增真实调用，不能回填旧失败原因。
本轮没有启动下一批campaign。当前已确认的问题是分阶段Build在交付前模型超时；后续
仍需围绕Build交付完成真实验证，普通流程历史2/2有效不推广为普遍稳定保证。
旧live-source审计因当前源码变化而拒绝属于预期行为，不得改旧manifest以通过检查。

以下为078封存终局与此前执行过程，当前代码状态以上述集成说明为准。

078终局已核验：两槽均Master计划验收且进入Build（2/2），但均约5280秒model/timeout，
没有checkpoint/续跑/subject回执/harness/评分，有效解0/2。subject原生耗时5280.390/
5280.378秒、退出码2，模型/工具事件16/21与14/21；HTTP状态、分数、完整失败usage/cost
和独立精确Master耗时均保持null，不能推断provider故障或提示修改的因果效果。
独立审计与root复验236证据SHA通过，37源码/114冻结文件/30历史锚点未变；watcher7684
退出0，174进度快照已保存，已知5个PID/5个PGID及可见argv/cwd关联无残留。
T078全部关闭，结果和最终证据见078 postrun/results.md。此批须先封存推送，再合入已审
079（b2ed0e9）；079未参加078，不自动追加campaign、重开失败槽或修改旧manifest。
当前目标仍是分阶段Build完成交付并经原生harness验证；普通流程历史2/2只是已验证背景。

以下078运行中记录为历史过程，当前状态以上述终局为准。

078进展22:25：第二份独立partial审计通过212证据SHA，钣金和邮政均已验收Master计划
且进入Build（2/2）；未续跑、尚无subject/harness回执或评分，两槽仍未决。观测为078
postrun/observations/20260910T142536754391Z.json/md。不能把交接计为有效解或因果结论。

078进展22:21：首次独立partial审计通过210证据SHA；邮政有效Master计划已验收并进入
Build，钣金仍Master。两槽仍未决，无subject/harness回执和分数。观测文件为078
postrun/observations/20260910T142109400271Z.json/md，不计有效解，不改变运行条件。

078已在登记`e76a3a341a90703f4ba91a9e14e33ca81a76c488`推送后于2026-09-10 22:17:13 +0800
唯一启动。dispatcher PID/PGID26135；slot1 worker26307、subject26308；slot2 worker26306、
subject26309。初始两槽均master_running，尚无计划/Build/回执/评分；root只读watcher
session7684每30秒写postrun/progress，measurement/保存启动与初始身份快照。
不要再次prepare/check-only/dry-run/launch，不改变已冻source/scripts/tests/input字节。
观察仅用078 campaign.py --summarize、postrun/audit.py；最终必须等两槽终止、独立审计、
核对进程并封存后才合入079。T078-05/06仍未关闭。

078已完成077规划职责的新测量登记准备，当前`.specify`指向
`specs/078-master-planning-role-measurement`。源码固定fba6ab8（不含079），同GLM-5.2、
钣金/邮政各一个新S槽，Master1200/build2400/reserve120秒、checkpoint32轮、共享5400秒/
200工具/800万tokens，一波并发2、至多一次同进程续跑，失败不补位。脚本沿用074固定
执行层，无额外076加载层，23个helper。328项隔离场景、176项root定向与独立审查通过。
已prepare一次，实际独立预审和328项登记dry-run通过；37源码/114冻结/30历史项一致。
manifest SHA605cfd030b3b65e9bc1995157f44acdbbbbe7e55837b6f4a27b7042afb996804，预审/dry-run
已原样镜像。登记提交推送后才能唯一launch；本段记录时尚未启动。T078-01至04完成，
05/06待真实终止与最终审计。不得重做prepare或并入079后继续使用当前登记。

079安全模型失败诊断已在隔离分支codex/model-failure-evidence提交推送b2ed0e9，暂未合入。
仅runtime/subject_diagnostics新增typed v3 fixedreason/response_status，原分类、解析接受、
预算/失败/评分权威不变；88新测试、1447隔离全仓、215独立回归与review通过。它不会参加
078，必须等078封存后合入；不能补写076原因或提供失败完整usage。本地worktree为
`.lunar/worktrees/feature079-model-failure-evidence`。

076已在`9ad2e1c`封存推送，随后合入077（isolated `1df9ae1`，merge `48e2b70`）。
当前`.specify`指向`specs/077-master-planning-role`，T076/T077全部关闭。主仓238项定向
回归、Ruff/Specify/diff通过，隔离全仓1359项通过。077只澄清Master规划职责：先交最小
Build计划，原始任务逐字保留，未知实现细节留给Build；system/tools/预算/评分权威不变。
它尚未参加真实评测，不能将离线通过当作有效解改善。当前目标仍是完成分阶段的有效解
交付；下一步用新预注册验证077，并针对本轮model_failed缺乏细分原因补足安全诊断。
不重开旧槽、不执行旧候选补分。076封存资料保持原字节；旧live-source审计因当前源码
改变而拒绝是预期行为，不得更新旧manifest来适配。

076终局：两槽均已结束，独立审计/root复验225证据SHA通过，37源码/111冻结文件/24历史
锚点未变。钣金1200.259秒model/timeout，无计划和Build；邮政2190.554秒model/model_failed，
首次通过含公开score词汇的Master计划并进入Build，已有solve.py和两份output文件，缺少
摘要/完成回执。两槽均无续跑/harness/评分，有效解0/2，完整失败usage/cost及分数均null。
model_failed没有HTTP状态码，不能断言具体provider原因或超时。watcher98576退出0，已知
9个PID/5个PGID及可见argv/cwd关联进程无残留。结果见076 postrun/results.md和final证据；
T076全部关闭，已先封存后合入077。不得重开失败槽、执行其候选补分或修改旧登记。

077已在隔离worktree完成Master职责澄清，独立审查通过：只改Master user prompt，前置
当前规划职责、原任务逐字保留、未知细节留给Build；不改system/tools/预算/原生评分权威。
14项新增测试、238项定向检查及1359项隔离全仓测试通过。首次全仓缺少8份.gitignored
历史证据，按封存SHA复制补齐后通过，未改测试或历史SHA。已在076封存推送后合入。

以下为076启动及此前历史；当前终局以上述说明为准。

076进展2026-09-10 17:32：独立只读审计确认邮政slot2计划验收且进入Build，计划含
combined_score/score/evaluator，201项证据SHA通过；这是075后首个真实合法阶段交接。
钣金slot1仍master_running；两槽均未决，尚无subject/harness回执、有效解或评分。
最新观测见076 postrun/observations/20260910T093257281442Z.json/md；不提前计有效，
不更改正在运行的预算/源码/输入。仍须等两槽结束后最终审计封存。

Feature076已启动075修复后的真实交接测量，`.specify`指向
`specs/076-public-plan-handoff-measurement`。源码固定`96d5a60`，GLM-5.2，钣金与邮政
各一个新S尝试，Master1200、build2400、reserve120秒，5400秒/200工具/800万tokens，
一波并发2、至多一次合作式续跑、不补位。311项隔离检查与独立审查通过，已prepare，
manifest SHA=`6690a02223aa3ea34bd5f88d9482d75d4a087857d69edd4245ac04479a321b76`。
实际独立预审和311项dry-run通过，37源码/111冻结文件/24历史锚点一致，原样报告已镜像。
登记`2916041947c49800b3dda0f5c463014292291aae`推送后，于2026-09-10 17:25:31 +0800
唯一启动；dispatcher PID/PGID93194，worker93363/93364，初始快照subject93365/93366。
两槽初始均master_running，尚无计划/Build/评分；T076-04关闭，05/06待结束和最终审计。
绝不能再次launch、prepare或执行要求未启动的preaudit/dry-run，不改源码/scripts/tests/
输入字节。观察只用076 campaign.py --summarize、postrun/audit.py；新缺陷在隔离worktree
处理，封存后再集成。075未解决或保证解决钣金规划超时；本轮只作描述性测量，历史不进
分母，不修改074封存SHA或重开旧槽。

最新状态：074已在`68b5e58`封存推送后，合入075公开计划词汇修复：isolated `065661f`，
merge `b5fc3b2`。当前`.specify`指向075，T074/T075全部关闭。主仓src/tests/.specify
与已审隔离版本相同，主仓260项定向回归/Ruff/Specify/diff通过，隔离全仓1316项通过。
修复移除计划文字与普通输出名的语义黑名单，保留结构、路径、身份和原生评分权威，
新增疑似凭据/当前API key输出路径拒绝。没有追加真实尝试；074全部封存文件与原版一致，
旧live-source审计现在会拒绝改变后的源码，这是预期结果，绝不能改历史SHA使其通过。
当前目标仍是让分阶段流程真实完成Master→Build→有效解；下一项需要用新登记验证075
后的实际交接与有效性，并根据证据处理规划超时。普通流程历史两例有效仍是已验证背景，
不把它推广成稳定保证，也不把本次0/2或离线通过改写成修复效果。
独立集成复核确认merge父链为seal68b5e58与reviewed065661f，138个产品/测试/Specify
文件与已审版本一致，074的68个Git封存文件逐字节保持；忽略的Python缓存不属封存证据。

074已于2026-09-10 14:30结束，最终独立审计/root复核205证据SHA通过，已知PID/PGID与
可见argv/cwd关联进程均无残留。钣金subject1200.203秒明确model/timeout；邮政167.136秒
runtime_failed，073解析器本次成功，但计划的公开objective scorer/combined_score被
workflow_checkpoint的score子串规则误拒绝。公开problem.json直接支持这些词汇。两槽
均无已验收计划/Build/续跑/subject或harness回执，分数与完整失败usage/cost均null，
有效解计数0/2。原生诊断与纯校验复现的区别、证据SHA及进程可见性限制见074 postrun/
results.md、final-audit.json、final-report.md、final-process-check.json和逐槽diagnostic。
本批源c28e498、登记27f7124b、manifest b154975d保持，T074全部关闭，不得重开失败槽。
075已在隔离分支修复语义词汇误拒绝并补充凭据路径拒绝，260定向/1316全仓及独立review
通过；先封存推送074，再合入075。075未参与本次测量，尚无修复后的真实有效解结论。

Feature074已启动修复后的新实评，`.specify`指向`074-corrected-staged-measurement`。
被测产品源码固定`c28e498`：钣金、邮政各一个全新S尝试，GLM-5.2，Master上限1200秒，
其余共享5400秒/200工具/800万tokens和一次合作式续跑不变。一波并发2、不补位；历史
069/072仅作背景，不进入分母。本轮分别验证计划验收、进入Build及最终exact-harness
有效解。测量脚本通过固定SHA复用原生执行/receipt与072只读阶段校验，只替换两槽登记
和汇总边界，不修改产品。137项新测试、239项完整隔离场景与独立交叉审查通过，登记已
生成：SHA `b154975d9557b9697fcdc7915de3ab7bb225165c6aaa1c6c0ab3f432a2123229`。
实际独立预审/dry-run已通过并镜像，37源码/99冻结文件/18历史锚点一致。登记提交
`27f7124b28ef9a7318c5f574a9ac97b16a718b9c`推送后于2026-09-10 14:10:22 +0800
唯一启动。dispatcher PID/PGID77166，slot1/2 worker77318/77317，初始快照观察到
subject PID/PGID77319/77320。首份独立partial审计通过181证据SHA，两槽均master_running，
当时还无计划/Build/receipt/评分。T074-04已关闭、05/06待结束与最终审计；绝不能再次
launch，不要修改源码、scripts、tests或输入字节。进度只读使用074 campaign.py --summarize
和postrun/audit.py；不要执行要求未启动状态的check-only/dry-run。启动与初始进程快照
见074 measurement/，独立观测见postrun/observations/；progress/为非权威只读进程/阶段快照。

最新代码状态：072最终证据已在`0a7f90e`封存推送后，合入073修复（merge `228b213`，
isolated `dd4d7f5`）。当前`.specify`指向073，T072与T073全部关闭。主仓src/tests与已审
隔离版本完全一致，167项主仓回归、Ruff、Specify和diff通过，沿用隔离全仓1147通过。
没有追加真实尝试；073尚无新的真实有效解结论。072旧manifest和全部终局资料不变，
其live-source审计会因当前parser源码变化而拒绝，这是预期行为，不能改旧SHA来适配。

2026-09-10 13:28之后最新结论：Feature072四槽均已终止，独立最终审计/进程检查通过。
300秒组0/2：钣金300.229s model/timeout，邮政300.123s runtime/timeout；1200秒组0/2：
邮政240.183s、钣金841.108s均返回了说明文字+json代码块，被整个响应的json.loads拒绝。
全部无已验收计划/Build/续跑/receipt/harness/评分，失败完整usage/cost和精确Master耗时
仍为null。233项证据SHA核对一致，37源码/92冻结文件/13历史锚点未变。已知PID/worker
PGID和可见argv/cwd关联进程均未发现存活；原始subject child IDs未记录，保留可见性限制。
结果见072 postrun/results.md、final-audit.json、final-report.md和final-process-check.json。
T072-05/06关闭；本批不补位、不回填，预注册09a7ea9及旧manifest永久保留。

针对格式问题，Feature073已在隔离worktree `.lunar/worktrees/feature073-master-plan-json-envelope`
分支codex/master-plan-json-envelope提交推送dd4d7f5。仅增加确定性的Master响应外壳解析，
原计划语义、路径、脱敏、预算和原生评分入口保持；93解析器+10集成测试通过，全仓1147
通过，独立review/Ruff/Specify/diff通过。新纯解析器可在内存接受两个已终止响应，但不
执行候选/模型/harness、不改失败结果。修复现已在072证据封存后合入，具体提交见本节开头。
后续目标：用新预注册验证修复后的Master→Build→独立有效解链条；本轮只证明放宽时间
仍会遭遇格式门槛，不能宣称1200秒普遍足够或已改善有效解率。

以下为本轮已完成的启动与准备过程：

Feature072已在预注册提交`09a7ea997df71e31bcdccaeba20f9140aa630b94`推送后，
于2026-09-10 13:09:00 +0800启动一次。后台dispatcher PID/PGID69681，第一波worker
69812/69813，初次进程快照观察到subject69814/69815。当前两槽都在Master，尚无计划、
Build或评分；后两槽等待波次屏障。不要再次launch，冻结源码/脚本/tests/input字节。
manifest SHA=`cbdb07e22b08a8944b9e80bf7f30cbd4057b931bd6128077dcf5da533834f830`，
37源码/92冻结文件/13历史锚点核对通过，实际预审与159项隔离dry-run均已提交并镜像。
当前观测见072 `measurement/launch-observation.json`、`initial-process-observation.json`和
`postrun/observations/20260910T050941Z.json`。后者通过169项证据检查，只是partial观测；
T072-05/06仍待全批完成/最终审计。只读进度使用072 campaign.py --summarize；完整观测
用072 postrun/audit.py，尚未完成时不能加--require-complete。不运行要求未启动的预审/dry-run。

2026-09-10 13:05左右最新工作：用户质疑300秒Master是否足够，已定义Feature072预算对照，
当前`.specify`指向`specs/072-master-budget-measurement`。在修正后源码`5c89e04`上，
同GLM-5.2/公开输入/exact harness新建四个S槽，仅master_seconds为300/1200两组；
顺序钣金300、邮政1200、钣金1200、邮政300，两波并发2。总5400秒/200工具/800万tokens，
build2400/reserve120/32轮合作边界及一次续跑不变，失败不补位，不运行WebAgent。
1037项全仓离线测试通过，独立实现交叉审查完成，正在冻结预注册与最终离线预审；本段
记录时尚未launch。旧069失败只作历史背景，不作修复后控制。精确Master耗时没有权威
独立计时，保持null；分别记录计划验收/Build阶段证据与最终有效解，不能从长预算成功
推出计划必定用了超过300秒。更明确角色/提示设计暂缓，避免与预算实验混在一起。

2026-09-10最新结论：Feature069四次预注册真实评测已全部结束并通过独立最终审计。
普通M有效2/2：钣金validity=1、overall/quality=0.999999；邮政validity=1、overall/quality
=1.0185。分阶段S有效0/2，两次均在300秒Master模型截止点失败，未进入Build或续跑，
失败评分及完整用量保留null。本批证明普通流程能在这两个历史高分case交付有效解；
单次case/arm样本不能证明稳定性或整体优劣，也不能据此评价续跑效果。最终资料见
`specs/069-webagent-normal-workflow/postrun/results.md`、`final-audit.json`和`final-report.md`。
测量源码始终为`80f5af1`；最终证据已在`26fc4a4`封存推送，随后按序合入070（`6def340`）
和071（`caf9a1f`），两项SDD任务均关闭。当前主仓`.specify`指向071；127项主仓定向测试、
Ruff、Specify、diff和独立集成复核通过。src/tests与已审071分支完全一致，沿用其946项
全量通过记录。修复只改tools.py：UTF-8截断保留完整前缀；嵌套argv字符串在执行前返回
可纠正诊断，不自动执行或重试。这些修复未参与刚结束的测量，也未新增模型调用。

当前目标：保持普通流程作为已验证的默认交付路径；先用Feature072预算对照验证Master
更长上限的阶段交接和最终交付，再决定是否调整规划职责/最小交接。无需为得到成功而补跑旧批，
不将普通流程2/2推广成普遍稳定保证，不扩张尚未真实触发的续跑能力。

以下保留历史过程；其中“运行中”“待合入”“保持源码冻结”等描述对应当时状态，
当前状态以本节开头的最终结果及已集成说明为准。

2026-09-09 最新转向：用户要求优先在 WebAgent 稳定高分的 case 上真实测量 Lunar。
Feature 068 已完成两例对照：sheet_metal_nesting、china_post_pickup_optimization；来自
平台 WebAgent/AgentServer（OpenCode）的同一 GLM-5.2 normal 实验，均三次有效且均分最高。
本次明确用 GLM-5.2，每例固定一次，5400 秒 / 200 工具 / 8000000 tokens；两个 case
已复算匹配官方 1.10.6。独立评分环境补齐钣金 evaluator 所需 pandas。钣金套料完成并
由 exact harness 判定 validity=1、overall=0.999999、quality=0.999999；邮政揽收优化
运行至 5400 秒超时，79 model turns/80 tool steps，无 subject receipt/harness/分数。
固定分母 valid=1/2，完成率 0.5；不同 case 不合并均分。结果、审计和 SHA 见 Feature 068。
暂停上下文功能开发，不改变旧 GLM-5.1 campaign，不运行 WebAgent。详见 Feature 068。

Feature 069 已完成可选 staged subject 接入、离线验证与四槽真实评测。钣金M与邮政M均
有效，overall分别0.999999和1.0185；邮政S和钣金S均在master超时失败。原设计目标为
`Master → Build → typed checkpoint → 至多一次同 attempt continuation`，通过同一预算改善交付率。
入口为 `run_subject_adapter(workflow_config=...)` 或 `effect-subject --workflow-config PATH`；
默认 normal workflow 不变。实际 master 模型输出的 JSON 计划经过验证后传给新的 build session，
所有阶段共用累计 tokens/cost/tool steps 和墙钟；receipt 汇总完整阶段用量，EffectTrialRunner
继续负责公共输入、receipt 和 exact harness 的唯一验证与评分边界。

2026-09-10 复核修正了早期独立 seam 的不足：不再丢弃 master 输出，不再把失败后部分 usage 当
完整用量，不允许重新初始化同一 attempt 或重置 deadline。首版只在完整工具轮次持久化后的
合作式边界续跑一次；API 超时/未知 usage、超预算或损坏 checkpoint 均终止，保留已有候选且不
产生 receipt。进程被杀后的恢复尚不支持。控制文件和 transcript 都增加了运行中软链替换检查。最终配置/master 摘要在落 checkpoint
前再次校验，避免模型末轮篡改冻结证据后仍生成 receipt。全仓 828 项测试通过（其中 101 项
staged 定向测试），Ruff、diff check 和独立审查通过。

真实 AgentLoop + 假模型、subject adapter/CLI、现有 trial gate + fixture harness 的离线测试已
覆盖计划传递、累计预算、单次续跑、失败不评分和身份/路径保护。它们不是私有 harness 实评，
不能据此声称有效解比例提高。T069-06 已完成：冻结4个新尝试，每个case各1次 control(M)
和staged(S)，两波并发2，顺序为钣金M/邮政S，然后钣金S/邮政M。两臂均GLM-5.2、
5400秒/200工具/800万tokens；S的master300/build2400/reserve120秒均包含在总时间内，
32个完整工具轮次可触发唯一一次同进程合作式续跑。失败不补位，未评分保留null。

产品源码冻结在`80f5af1`，预注册SHA为
`07781f3390586e49c2c521012e7981350c06215e6c7103a865a97f25597e423e`；
37源码、74执行/测试/输入文件、8个历史证据锚点已固定。独立审计通过，隔离dry-run26项、
全仓874项测试通过，未调用真实模型。协议与证据见`specs/069-webagent-normal-workflow/measurement/`。
汇总纯读取native state/record/report，不调用会恢复备份的读取路径；启动与退出证据须一致。
T069-07进行中：预注册已提交推送`454b521`，本机`.lunar/real-eval-glm-5.2-staged-20260910/`
于2026-09-10 10:19:43 +0800启动；父进程PID48660，第一波slot1/2已进入subject，
邮政S当时为master_running，尚无终止或评分。后台父进程会在第一波两槽均终止后启动
slot3/4；绝不能再次运行`--launch`。当前启动快照见measurement/launch-observation.json，
它不是最终结果。仅用`campaign.py --summarize`读取进度，勿运行要求未启动的check-only/dry-run。
2026-09-10 10:34进度：slot2邮政S已在master阶段300秒模型超时，subject退出2，
15模型响应/19工具调用，尚无master计划/build/resume/receipt/harness/分数；worker退出0仅
代表失败证据正常保存。当时slot1钣金M仍运行，slot3/4尚在波次屏障后，不能把该观测当成全部失败。
诊断/记录/SHA经独立核验，机器与文字观测见measurement/interim-slot-002.json和.md。

本槽还暴露一个确定性工具bug：28,878字节UTF8有效CSV的20,000字节预览截断汉字，误报编码
错误；另两次命令把argv数组嵌套编码成字符串导致可执行名错误。三次错误缺少逐调用耗时，
不能断言它们单独造成master超时。Feature070只在隔离worktree
`.lunar/worktrees/feature070-utf8-prefix`（分支`codex/read-file-utf8-prefix`）修复UTF8边界，
不修改正在测量的主仓。Feature070已在隔离分支提交`42c7f6e`，45项边界/复现测试与
919项全仓测试通过，独立审查、Ruff、Specify和diff检查通过；等本批结束并审计后才合入。
主仓仍为原874项测试与冻结产品源码，本批不补跑。

随后完成Feature071：在`.lunar/worktrees/feature071-command-argv`、分支
`codex/command-argv-diagnostic`（基于070）提交`5a39aa4`，为JSON数组被写成字符串的
command返回静态纠正提示，启动前拒绝，不自动转换/执行/重试；真正argv与普通string保持。
27项新增测试、946项隔离全仓测试与独立审查通过，Ruff/Specify/diff通过。测试证明模型
自行纠正后的两次工具调用只启动一次fake进程，原始参数与累计用量不重置。070/071均已
推送各自分支，等待本轮终止并审计后按顺序合入；主仓`.specify`仍指向069。

再次只读核对WebAgent固定`e24df25`发现：它的300秒是`agent_wait`等待窗口，超时后worker
继续运行；Lunar的300秒master硬截止与最终JSON计划门槛是自己的实验设计，不能称为
WebAgent同等配置。实际v2.5 master协调多角色、写PLAN.md并派发solver，权限并非只读。
详见`docs/webagent-master-comparison-20260910.md`。历史高分记录未绑定这一代码commit，
因此只把角色/交付契约作为本批结束后的假设，不中途调整规划策略。

2026-09-10 10:49进度：钣金M仍在运行，已有分析脚本但无receipt/评分；邮政S的失败仍为
已审计记录，后两例继续等待第一波结束。源码37、冻结输入/测试74、历史锚点8项SHA均未变。

2026-09-10 11:05只读观测：slot1仍未决，slot2失败，slot3/4未启动。新增
`specs/069-webagent-normal-workflow/postrun/`审计与中文报告工具，位于冻结dispatcher/tests
之外；29项离线测试、Ruff和独立复核通过，没有模型调用。审计通过原worker逐槽核对实际
private case/extractor/evaluator，验证注册提交、全部冻结文件、源码Git blobs与实际import
路径，再核对唯一attempt、wave顺序和native record/state/report/receipt链。它不启动或
恢复运行、不写campaign文件；`--require-complete`对当前未完成批次明确拒绝最终验收。
历史分数投影逐项对照已冻结原记录，null和大于1的分数原样保留，不加入本批分母。
实际审计及报告已保存为`postrun/observations/20260910T030511Z.json`和`.md`，共155个
证据文件；这只是partial observation。外层时间一致性检查有明示2秒容差，不增加预算；
最终仍须人工确认本批进程退出。T069-07保持未完成，全部终止后用只读工具封存最终审计、
报告并独立复核，再合入070/071；合入后保留原Git/SHA锚点，不改历史manifest适配新源码。

2026-09-10 11:14进度：slot1钣金M已完成exact harness评分，validity=1、overall/quality
=0.999999。Subject 3068.032秒，harness 122.493秒，native run 3190.563秒；实际模型
GLM-5.2，30次模型交互，subject累计input719940/output149337/total869277 tokens，
费用null，以上用量不包含extractor。独立复核subject/harness回执、record/state/report/
outcome链及private harness实际字节通过；37/74/8冻结SHA未变。分数与上一批钣金Lunar
相同，但历史样本不进入本批分母。slot3/4已于11:12:53 +0800在第一波全部结束后自动
启动；本批仍未完成。新partial审计及报告为`postrun/observations/20260910T031419Z.json`
和`.md`，核验185个证据文件；成功槽详细口径见`postrun/slot-001-success.md`。

2026-09-10 11:18进度：slot3钣金S也在master的300秒模型截止点失败，subject退出2、
耗时300.222秒，native300237ms；诊断model/timeout，7个模型响应、11次工具调用，
无subject/harness回执，评分与完整usage为null，resume_used=false。两槽S已全部终止，
本臂有效解0/2；两次均未进入Build或触发续跑，不能由此评价续跑后的求解效果。slot4邮政M
仍未决，全批T069-07仍未完成，不提前计算普通臂的最终完成率。最新partial观测见
`postrun/observations/20260910T031858Z.json`与`.md`，核验196个证据文件。继续等待唯一
剩余的已注册attempt终止，主仓源码/dispatcher/tests保持冻结，070/071暂不合入。
Slot3 transcript经独立只读核验有11个唯一call/result完整配对：read_file4、list_dir3、
run_command4；其中1次run_command把JSON argv嵌套编码成string，触发FileNotFoundError，
与071所覆盖的模式相同。无其他工具错误，不能由此把300秒全部归因于这一次错误。
workflow的初始0计数不代表零消费；checkpoints目录存在但为空，无master计划/build
transcript/receipt/harness。17项证据SHA及分析见`postrun/observations/slot-003-master-failure.json`。

随后补充两份已终止Master的行为分析，见`postrun/master-behavior-analysis.md`和`.json`。
两槽都没有成功返回并持久化的最终响应，模型超时发生在计划JSON解析之前，并非已返回的
计划被校验拒绝；不能据此断言服务端未生成文本。read_file/list_dir没有同路径重复；成功的Python数据探查分别7/3次，
重复加载公开输入进行不同统计，未见写候选或执行solver。参数错误后均有自主纠正，
缺少逐调用耗时，不能单独归因。实际master复用通用系统角色和normal求解任务，加附加
planning说明；代码向每次请求副本提供master剩余时间，但不持久化该提示。不能说模型
不知道截止时间，亦无法区分网络、排队与生成耗时。角色混合仍是待验证解释。下一轮角色/
交接设计仍待本批结束后另行SDD，当前不改预算或启动新尝试。

2026-09-10 12:09:16 +0800，全批终止。Slot4 subject3331.589秒、harness50.244秒、native
3381.900秒，GLM-5.2/provider_observed、59次模型交互，input2010306/output138981/
total2149287 tokens；用量仅subject、不含extractor，费用null。原始harness认可validity=1、
overall/quality=1.0185，大于1原样保留。12:11:50只读`--require-complete`最终审计通过：
passed/complete/final_acceptance均true，212项证据SHA经独立重算一致，37源码、74冻结
文件及8历史锚点全未变。T069-07已关闭；summary SHA为
`712e78755f61ce360a3249abe29624ec9aef291936b7209adba075d18938d450`，final audit SHA为
`3175509fe7d2df7210047ec956ad2f24049189524adfe5670586704ec6cdb2e7`。
独立进程检查及root复核均未发现已知PID/PGID、可见命令参数或cwd关联的本批残留；
详见`postrun/final-process-check.json`，保留child PID未记录等覆盖范围限制。全部四槽
各一次，未重跑WebAgent、未请求新平台数据、未补位、未复制旧候选。文中带时间的运行中
段落是历史观测；本批现在已封存，后续源码变化不得改写manifest来通过旧冻结检查。

本批运行期间产品源码、measurement脚本和tests保持冻结，现已完成按case报告和独立审计。此前结果不回填，不重新运行WebAgent。源码SHA和run/attempt
由预注册worker实际核验；adapter继续核验request/case/profile/limits绑定。模型密钥仅通过
用户已授权的CC Switch读取并传进相应子进程环境，不写入证据。设计见`specs/069-webagent-normal-workflow/`。

Feature 067 已完成使用新预算诊断的两槽真实 GLM 测量。两次均明确触发
200000 token ceiling，subject 耗时 488.371 / 522.781 秒，valid=0/2、scored=0，完整失败
usage 和分数仍为 null。新诊断与独立审计均通过，详见第 25 节；没有补位或回填历史。
Feature 066 已补齐后续预算失败的具体触发项与有界部分用量证据，保持
旧版诊断、成功回执和评分/恢复边界兼容；全仓 726 项测试及独立审查通过，详见第 24 节。
Feature 066 开发轮没有真实模型调用或回填旧记录。此前 Feature 065 已完成 Feature 063/064 新变体
的两槽真实 GLM 实评。两次均在
subject 阶段 runtime/budget_exceeded，无产物、receipt 或评分；valid=0/2，评分和未知
usage 为 null。已独立核验并保留负结果，详见第 23 节。Feature 064 代码为 `6189e50`，
profile 预算提示、命令剩余时间收紧、write_file 原子替换和超时输出修复已通过 667 项测试。
此前 Feature 063 已提交并推送于 `fef89a8`，吸收 WebAgent v2.5/base `e24df25` 的工具参数
契约思路；分支审查见第 21 节和 `docs/webagent-v25-review-20260909.md`。

Feature 058 已提交并推送于 `1ae1893`，新增只读预检及公司平台 baseline 来源记录。
Feature 059 已完成普通求解和 isolated compiler/audit 调用的模型预算、超时边界修复。
Feature 059 已提交于 `503fe0a`。Feature 060 已提交并推送于 `f4b7ba9`，修复结构化输出验收
绕过，统一普通/委派 Solver、候选程序执行和最终产物生成的独立输出校验。
用户再次确认现有实验数据已足够；不运行 WebAgent，不再要求补 WebAgent 数据。
2026-09-08 用户进一步要求推进真实 Lunar 评测：当前优先级已切换为运行首个真实 trial，
不再以新功能开发作为前置条件。下文旧轮次的“本轮不启动真实 trial”仅是历史记录。
已通过用户授权的 CC Switch 接通模型，完成 `supply_chain_inventory` 的首个真实 1 run ×
1 round：有效性 `1.0`、得分 `0.2079`，历史最佳 `0.3496`。独立的 2 runs × 5 rounds
试验已结束，但两个 run 均在首轮 subject 退出、未进入评分；最新证据与待修复项见第 16 节。
用户随后要求改用 WebAgent 已有记录中的较弱求解模型：已选定并实际验证 `glm-5.1`，
后续不再启动 `gpt-5.6-sol` 求解。Feature 061 已补齐此前失败暴露的安全诊断缺口；
GLM 独立单 case 实评已执行，在 900 秒预算内未产出候选、没有进入评分，安全诊断为
model timeout。当前模型选择、结果与证据边界见第 17–18 节。

以下保留 2026-09-06 续接时的历史提交记录：

```text
4a61044 test: cover nested candidate manifest traversal
46d576d docs: update handoff for failure statistics
32561c9 feat: report deep evolution failure statistics
558f510 docs: record continuation findings
f633dde fix: allow candidate interpreter startup before timeout
b3df70e docs: add lunar agent handoff
edaa4a6 feat: add controlled deep evolution feedback
```

此前收口已修复普通/深度效果试验的记录权威和深度 round receipt 完整性，更新 Feature
048/051/052 文档，并补齐官方 FM-Eval AgentServer normal-mode comparator。变更已按指定身份
提交并推送；完成时保持 `main == origin/main`。

## 2. 产品目标和设计边界

Lunar-Agent 的目标是一个独立、本地、可被其他 Agent 调用的算法问题 Agent：

- 用户可以直接运行；Codex、Hermes、OpenClaw 等也可以把它当作 CLI 子进程调用。
- 不要求用户机器预装 Hermes、OpenCode、Codex 或某个全局配置目录。
- 内部自带 Agent runtime 骨架，同时允许显式接入 OpenAI-compatible endpoint、subprocess
  或 mock runtime。
- 解决算法/组合优化问题，输出结构化文件、数据和可验证报告，而不只是对话文本。
- 借鉴 WebAgent 的 clarify/build/evolve、fresh loop、评估、恢复和证据边界，但不复制其
  服务化、队列、计费、远端 workspace 架构。
- 同时保留三类搜索入口：`loop`、`population`、显式 `OpenEvolve` adapter。
- 所有评分必须由独立 evaluator/harness 给出，Agent 不能自报分数。

当前总体架构可看：

- [架构文档](/Users/liminghan/Documents/lunar_agent/docs/architecture.md)
- [项目 README](/Users/liminghan/Documents/lunar_agent/README.md)

核心链路：

```text
CLI / parent Agent
        ↓
LocalController + DomainRouter + MasterPolicy
        ↓
AlgorithmProblemContract / plan / output contract
        ↓
Runtime Adapter
  mock | subprocess | OpenAI-compatible | AgentLoopRuntime
        ↓
loop | population | openevolve adapter
        ↓
candidate archive → execution/evaluator → verified artifacts/data/report
```

深度效果评测另有独立边界：

```text
fresh subject round
        ↓
exact private extractor/evaluator harness
        ↓
bounded RoundFeedback
        ↓
fresh subject round + shared candidate workspace
```

## 3. 已完成工作

### Feature 001–011：独立 Agent 基础和恢复

已完成 standalone local Agent、CLI/TUI 基础、Hermes-inspired bounded tool loop、模型 runtime
adapter、交互恢复、transcript、Master Policy、plan contract、DAG 调度、artifact acceptance、
evidence-guided recovery、隔离 worker pool、retry feedback。

对应目录：

```text
specs/001-standalone-local-agent
specs/002-webagent-effect-parity
specs/003-hermes-inspired-local-agent
specs/004-interactive-session-recovery
specs/005-session-transcript-recovery
specs/006-master-policy-plan-contract
specs/007-domain-routing-solver-evaluator
specs/008-artifact-acceptance-contracts
specs/009-evidence-guided-recovery
specs/010-local-isolated-worker-pool
specs/011-verified-retry-feedback
```

### Feature 012–026：算法任务、Agent adapter 和演化运行时

已完成算法问题契约、loop/population/OpenEvolve 入口、Agent delegation、Agent-backed
generator/evaluator、portfolio、evaluator ensemble、runtime-backed evolution、执行验证、
对话式算法任务、role DAG、evolution agent loop、结果 handoff、provenance、verified feedback。

### Feature 027–036：benchmark、运行 profile 和结构化输出

已完成 evolution benchmark、unified benchmark、runtime profile benchmark、Agent evidence、
structured algorithm outputs、input staging、role evidence、runtime artifact envelope、
conversational evolution handoff、evolved output materialization。

### Feature 037–047：执行闭环、评估器安全和搜索增强

已完成 execution-grounded evolution/refinement、objective harness handoff、frozen evaluator
bundle、private data profile、adversarial evaluator audit、solver scoring contract、verified
experiment memory、adaptive search orchestration、contract-driven algorithm playbooks、
quality-diversity population。

对应重点目录：

```text
specs/037-execution-grounded-evolution
specs/039-execution-grounded-refinement
specs/040-frozen-evaluator-bundle
specs/041-private-data-profiling
specs/042-adversarial-evaluator-audit
specs/043-solver-scoring-contract
specs/044-verified-experiment-memory
specs/045-adaptive-search-orchestration
specs/046-contract-driven-algorithm-playbooks
specs/047-quality-diversity-population
```

### Feature 048–050：Famou-Bench 效果层

- Feature 048：导入历史结果，比较单 case 的 Lunar best 与通用 baseline historical best，
  只允许独立 harness 提供分数。
- Feature 049：加入可执行的 subject/harness adapter，支持 public projection、private
  extractor/evaluator、receipt 和环境隔离边界。
- Feature 050：生成 content-addressed effect kit，冻结 suite、case digest、public file ledger、
  evaluator/extractor digest，避免 benchmark 内容漂移。

本地已准备好经过官方 publication 身份校验的 `supply_chain_inventory` kit 和历史 comparator：

```text
.lunar/famou-kit-real-001/
```

该目录被 `.gitignore` 忽略。baseline 来自 FM-Eval 只读 Query 的实验
`fmexp-1fae1f63-b54a-400b-9ca4-118a4c6387f9`，三次历史分数为
`0.3496 / 0.3496 / 0.2415`，historical best 为 `0.3496`。选中 case 的三条结果都满足
FM-Eval conclusion eligibility；整个来源实验本身仍保留 `failed/partially_valid` 状态，不能把
case slice 的可比较性扩张成整个实验成功。该实验的 adapter 是 `agentserver` 且
`deep_evolution=false`，所以它是官方 FM-Eval AgentServer normal-mode comparator，不能称为
WebAgent historical baseline；严格的 WebAgent 比较仍需同 publication/case 的
`adapter=webagent` export。

### Feature 051：五轮深度演化效果试验

目录：

```text
specs/051-deep-evolution-effect-trial/
src/famou/deep_effect_trial.py
tests/test_deep_effect_trial.py
```

命令：

```bash
lunar-agent effect-deep-trial ...
```

行为：默认 5 个 outer rounds；每轮启动新的无记忆 subject 进程；共享 attempt workspace；
每轮执行 exact private harness；每轮原子保存 logical-run record；`--resume` 校验 suite、
baseline、case、receipt、harness 和配置身份；报告 round curve、best、P50/P90、gain 和
milestone。

本次进一步加固了效果试验的恢复和评分权威：

- built-in deep subject receipt 用 `request_sha256` 绑定 canonical request；旧的已完成
  receipt/record 仍可读取，但未登记 subject round 没有绑定摘要就不能复用；
- 恢复时逐项复核 subject 的模型、evidence、turns、usage，以及 harness 的 extraction、
  validity、overall、quality、detail metrics 和已记录的 harness request 摘要；
- 已有 request-bound subject receipt 且 harness 目录安全时，未写入 durable round 的 harness
  目录会删除并由 private harness 重评分；harness 早于 subject receipt 或路径不安全会 fail
  closed。未在 state 中登记摘要的普通/深度 `record.json` 也不能自动成为权威记录；
- 只有 `incomplete_rounds` 可继续原 attempt；进程或边界失败在下一次恢复时创建新 attempt，
  并保留旧目录作为证据；
- control、state、record、attempt 路径检查完整祖先 symlink 链；subject 不能预建同级
  harness workspace；
- `record.previous.json` journal 覆盖 `record.json` 已替换而 `state.json` 尚未登记新摘要的
  中断窗口，只允许回滚到与 state 摘要精确匹配的上一版本。

### Feature 052：受控 RoundFeedback 契约

目录：

```text
specs/052-deep-evolution-feedback-contract/
src/famou/deep_feedback.py
tests/test_deep_feedback.py
```

当前反馈不再是裸的 validity/quality/overall 三个分数，而是严格、有限的 projection：

- finite scores、score delta、best round；
- 通用 allowlisted detail metrics；
- 候选文件的相对路径、大小、SHA-256，不传文件内容；
- `invalid_candidate`、`evaluation_failed` 等有限失败类别；
- `repair_validity`、`repair_evaluation`、`change_search_strategy`、`refine_best`、
  `preserve_best_and_probe` 指令；
- 停滞窗口默认 2，可由 `--stagnation-rounds` 配置并冻结进 state identity。

subject receipt 仍然不允许携带分数；分数只能来自 private harness。

### Feature 053：深度试验失败统计

目录：

```text
specs/053-deep-effect-failure-statistics
```

深度试验的每个 case 报告现在包含有界 `failure_statistics` 投影：逻辑 run 错误码、round
反馈类别、已记录/已完成 round 数、超时计数，以及覆盖每个配置 round（含空 round）的固定
明细。该投影只从已验证的持久记录派生，不创建分数，也不改变 private harness 的评分权威。
本次还修复了候选物化的极短超时可靠性：候选解释器启动保留 50ms 下限，避免正常候选在
启动阶段被误判超时；较长预算保持原值。

### Feature 054–055：模型 profile、成本控制与 runtime 集成

目录：

```text
specs/054-model-profiles-cost-control/
specs/055-runtime-model-profile-integration/
src/famou/profiles.py
src/famou/model_profile.py
```

`ModelProfile` 提供无凭据的模型身份、thinking budget、步数/超时、token 和 micro-USD 成本
上限；`UsageLedger` 对每轮规范化用量做整数计费并在超限前拒绝。`AgentLoopRuntime` 可选接入
profile，使用 profile 的默认 timeout 和 step 上限，在每轮模型响应进入工具动作前校验 token/cost
预算，并在成功结果中报告 profile 名称和可用的 `cost_micros`。没有 profile 的既有调用保持原有
行为；同一 runtime 复用时账本按 invocation 重置。

### Feature 056：CLI runtime profile provenance

目录：

```text
specs/056-cli-runtime-model-profile-provenance/
```

普通 `run`、`solve`、`resume`、`answer` 和 `plan` 的 `--agent-loop` 现在可通过
`--model-profile PATH` 加载有界 JSON `ModelProfile`。profile 必须是非 symlink 的普通 UTF-8
JSON 文件，内容经 `ModelProfile.from_dict` 校验；它可提供默认 model，并把 timeout、步数、
token 和成本限制传入 `HermesSessionRuntime`。没有 `--agent-loop` 时显式 profile 会在运行前
拒绝。detached 子进程只传播 profile 路径，API key 仍通过环境变量传递。solve 的 compiler
fingerprint 包含 profile 的 canonical SHA-256，profile 变更会拒绝 conversational resume。
one-shot runtime、`run_isolated`、effect adapter 和 evolution/benchmark 专用 runtime 参数
仍未接入该 CLI profile，后续应单独设计。

## 4. 本地知识库索引

知识库根目录：

```text
/Users/liminghan/Documents/fm/ku-offline-D15p9TZGvN/
```

正文通常在 `raw/content/<docGuid>.json`，同步日志在 `archive.log`，离线渲染页面在
`docs/<docGuid>/index.html`。

重点文档：

| 文档 | docGuid | 作用 |
|---|---|---|
| 深度演化 PRD | `sqWURJ5cTnE_Z7` | Session/Experiment 生命周期、Top 5、可恢复和用户可见演化图谱 |
| v2.5 深度演化工具集设计 | `7bveCuILHL_BnP` | evolve_create/update/continue/cancel/list/status/sync 七工具和窄控制面 |
| web agent 与 famou-v2 深度演化打通链路梳理 | `y0gVkzefWknA6h` | Console → AgentServer → AgentRunner、异步进度回调 |
| 深度演化阶段 webagent loop vs famou-v2 evolve | `qx9kRYpa6zTQmP` | 同模型 loop 与 population/pipeline 对比、reward hacking 证据 |
| 基于 famou-bench-v2 的深度演化阶段模型评测报告 | `YfEcoKAjskbg3P` | 100 轮模型对比、token/时长/成本、格式失败影响 |
| webagent benchmark 测评工程方案（二期） | `xOvDqBtdcHUO16` | fm-eval workload、评测服务化和 benchmark 接入方案 |
| famou-v2 Island & Population Ablation | `jncZRh92LHwYV0` | population/island 消融证据，后续比较 population 时查阅 |

面试/架构辅助文档：

```text
/Users/liminghan/Documents/fm/面经/合集/伐谋agent架构细节面试小抄.md
/Users/liminghan/Documents/fm/面经/合集/项目二-伐谋WebAgent与Workspace.md
/Users/liminghan/Documents/fm/面经/合集/webagent-架构图.svg
```

## 5. 可查阅代码仓库

### Lunar-Agent

```text
本地：/Users/liminghan/Documents/lunar_agent
远端：git@github.com:vchive/Lunar-Agent.git
分支：main
```

### WebAgent

```text
本地：/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/webagent
远端：https://liminghan01@icode.baidu.com/baidu/acg-fm/webagent
```

已知分支：

```text
origin/master
origin/famou-v2.5/base
origin/famou-v2.5/evolve_tool
origin/famou-v2.5/master-agent
origin/multi-round
origin/memory_card
origin/famou/memory
origin/feature/or-agent
```

重点代码检索词：`evolve`、`loop`、`population`、`workspace`、`agentic loop`、`master agent`、
`analyst`、`executor`、`callback`。

### Famou-Bench

```text
本地：/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/famou-bench
远端：https://liminghan01@icode.baidu.com/baidu/acg-fm/famou-bench
当前本地分支：agentco-bench-lite
```

真实 case 示例：

```text
/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/famou-bench/03_assignment/supply_chain_inventory
```

该 case 已包含 `instruction.md`、`data/`、`tests/extractor_agent.py`、`tests/evaluator.py`、
`tests/baseline/reference_metrics.json`，但 `reference_metrics.json` 不是 FM-Eval historical
run export，不能直接冒充 WebAgent baseline。

### FM-Eval

```text
本地：/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/fm-eval
远端：https://liminghan01@icode.baidu.com/baidu/acg-fm/fm-eval
```

重点：`container_runtime/harness/`、`tests/test_harness_equivalence.py`、
`tests/golden/harness_equiv/`、`tools/release/`、`service/`。

### Famou-v2

```text
本地：/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/famou-v2
远端：https://liminghan01@icode.baidu.com/baidu/acg-fm/famou-v2
```

### 外部参考

```text
OpenEvolve: https://github.com/algorithmicsuperintelligence/openevolve
DeepSeek Harness: https://github.com/deepseek-ai/deepseek-harness
Lunar-Agent remote: https://github.com/vchive/Lunar-Agent
```

OpenEvolve 在 Lunar 里是 adapter，不是必须依赖；Hermes/OpenCode/OpenClaw 同样是可选外部
调用方或显式 runtime，不是 Lunar 的部署前置条件。

## 6. 下一步任务（按优先级）

083的可选主机防空闲休眠保护已完成实现、独立复核与全量验证。下一项单独定义
请求时限及有限传输恢复的SDD，明确物理尝试计数、共享期限和失败usage
未知时的预算边界。需要验证效果时另作GLM-5.2新登记，用已有高分case背景测分阶段
Master→Build→原生harness有效解，不重开082/078旧槽，也不升级模型或重跑WebAgent。
主机保护本身不能证明有效解率提升。当前实现和验证状态以第1节及083 validation为准。

以下P0/P1及来源说明保留为早期历史，不再作为当前待执行任务。

### 历史 P0：Feature 068 的高分案例真实测量（已完成）

用户要求先选 WebAgent 稳定高分 case 验证 Lunar 能力。已只读查询既有平台逐次记录，
在最新选中的 GLM-5.2 normal 实验中按三次均有效/eligible、均分降序选定钣金套料和
邮政揽收优化。两例各运行一次 Lunar，预注册更接近历史资源规模的有界预算，全部结果
保留。详细协议在 `specs/068-high-score-case-measurement/`；不把 AgentServer/OpenCode
部署身份说成已核实的 v2.5 commit，不把 provider/工具/缓存/未知配置差异说成完全公平复现。

### P1（已暂停）：围绕已观测的输入预算压力，审查并设计最小上下文改动

第 19–20 节的历史解释和固定两槽测量已完成，失败就是该配置下的正式结果。当前按
第 21–23 节完成 WebAgent 设计借鉴及其实评：Feature 063/064 的两槽新变体仍未完成，
没有观察到本批完成率改善；不能宣称其中某个改动的因果效果。Feature 066 补齐诊断后，
Feature 067 的独立两槽测量已明确这两个新槽触发 token ceiling（第 25 节）。两次最后
请求仅输入 tokens（25670 / 25488）就超过此前剩余额度（20433 / 1880），这支持优先
离线审查完整消息回放、工具读取/输出和上下文体积，再用 SDD 选择最小预算管理改动。
方案需保留公开任务、工具调用/结果配对、候选与评分权威边界，并在原 `glm-5.1` 和预算下
另行预注册固定次数测量；只提前拒绝下一请求不能证明求解效果提升。大文件分页、UTF-8
截断和上下文归档仍是独立候选，不能当作已定位的具体根因。
不追加任何已结束 campaign 的第三次尝试，不为了成功而补位，不修改历史结果，不再运行 WebAgent
或索要数据。历史失败的具体预算触发项仍未知，完整失败消耗仍不能由部分观测推定。

以下保留既有测量所用的冻结来源与执行边界：

官方 publication kit 和 AgentServer normal-mode historical comparator 已就绪，不需要手填
历史分数：

```text
suite:    .lunar/famou-kit-real-001/suite.json
projection: .lunar/famou-kit-real-001/baseline-agentserver.json
raw:      .lunar/famou-kit-real-001/fm-eval-results.json
case:     supply_chain_inventory
baseline model (historical): gpt-5.6-sol
current Lunar solver:        glm-5.1
adapter:  agentserver (deep_evolution=false)
```

关键摘要：

```text
suite SHA-256:    1701995e8f65d9bd2ba73e840b870c9427fce27107e14048cffb34d594a04e46
baseline SHA-256: 17e308b4eca5cdc1ebf334daf9c8956fe8871230c1ddcd38872d56f66466a34b
raw SHA-256:      fa41c138ed3c73a50dd17e9e99704b41a079aef15ab45b1a6bdd65c3897c889d
```

`provenance.json` 保存只读查询、模型观测和来源实验状态；
`publication-identity-verification.json` 保存发布期 FM-Eval SDK commit
`b17023d3f849f3312f8fc79f366b0c18495ee726` 的复算证据。旧 `baseline.json` 没有内嵌 adapter
provenance，保留作历史审计，SHA-256 为
`355a8f1dee33532e720711a9c72988e83f61b4f9af8e4187e51ed3e859579440`。Feature 058 从同一 raw
export 离线生成 `baseline-agentserver.json`，明确保存 `source=company-platform` 和
`adapter=agentserver`；除来源字段外，模型、case 身份和全部 per-run 值与旧 projection 一致。
`baseline-agentserver-provenance.json` 记录本次输入/输出摘要和一致性复核。

当前任务复用冻结 suite/harness，已有 AgentServer baseline 仅保留审计；不补跑 WebAgent 或搜集新的 WebAgent export。
用户最新模型要求优先：已有单 case baseline 的模型是 GPT，与新选 GLM 不同；旧 baseline
保留作历史证据，不传入 GLM 的同模型比较、不改写模型标签。离线 WebAgent 报告足以确认
GLM 求解模型选择，但其中跨 case 聚合值不能伪造成此 case 的 per-run baseline。
effect protocol 的规范机器字段是 `baseline_historical_best`；显式 WebAgent provenance 或
旧 `fm-eval` 无 provenance 的兼容路径还会输出 `webagent_historical_best` 别名。因此当前
示例使用带明确来源的新 projection。只有将来另行要求 WebAgent-specific 比较时，才需要
取得相同 publication、CaseRevision 和 harness 身份下 `adapter=webagent` 的 export。
`effect-baseline` 在默认 `webagent` 模式下会拒绝该 export 的显式 `agentserver` evidence；使用
`--adapter-kind agentserver --baseline-source company-platform` 可离线生成带明确来源的
`baseline-agentserver.json`。冲突的 adapter evidence 仍会被拒绝；缺少 adapter metadata 的
legacy export 继续兼容，但必须另外保留来源证明。

2026-09-08 初次检查时，普通 shell 中没有
`FAMOU_MODEL_ENDPOINT`、
`FAMOU_API_KEY`、`FAMOU_MODEL`、`ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_BASE_URL`、
`ANTHROPIC_MODEL`、`OPENAI_API_KEY`、`OPENAI_BASE_URL` 或 `ANTHROPIC_API_KEY`。本轮已另行创建
专用 `.lunar/harness-venv-sdk-0.1.81/` 并安装、验证评分依赖，见第 15 节；无需在项目 venv 中
重复安装。来源实验的 extractor 冻结为 Anthropic API、模型
`glm-5.2`，发布期 FM-Eval harness 锁定 `claude-agent-sdk==0.1.81`；exact extractor 必须使用
包含对应依赖、与冻结身份相符且获授权的运行环境，并显式设置
`ANTHROPIC_MODEL=glm-5.2`。密钥只通过显式环境传递，不能写入仓库、request、receipt 或
report，也不能用 Codex/Claude 的本机登录态冒充 extractor 配置。随后用户明确授权复用
CC Switch 当前 provider 的 API 配置；第 16 节记录了只读接入、显式环境注入及首轮真实结果。
普通 shell 中没有这些变量已不再是启动阻塞。

当前执行步骤：

1. 先读第 17 节，检查 `.lunar/real-eval-glm-5.1-20260908/started.json`、`report.json`
   和 `attempt-001/diagnostics/`，保留已运行 attempts；不要重复启动已消费的实验目录。
2. 当前 solver 只用 `glm-5.1`，extractor 保持 `glm-5.2` 与 SDK `0.1.81`，继续通过
   已授权的 CC Switch 只读加载连接环境，不再运行旧 GPT 脚本。
3. 单 case 实评由本机 `run_single.py` 调用已有 subject/exact harness adapters，预先验证
   冻结输入，成功后检查实际 receipt 与模型身份。只有 private harness 的实际结果可评分。
4. 本次没有 GLM per-run baseline，仅报告独立分数、用时与可观测用量；不计算匹配模型的
   delta/breakthrough，不用跨 case 聚合分代替单 case 历史结果。
5. 这两个冻结 slot 已完成；按第 20 节汇总失败与分母。未来新的 baseline-free 批量测量
   必须单独冻结 manifest 和 SDD，不放宽现有 comparative runner 的模型一致性 guard。

### P1：修复真实 case 适配差距

真实 Famou-Bench 的 extractor 使用 `claude_agent_sdk`，并可能需要 case-specific 的数据
语义。执行真实试验后，若 Lunar 写出的文件不能被 extractor 识别，优先补充：

- case-specific output contract / `OutputSpec`；
- subject prompt 的目标文件提示；
- solution artifact materialization；
- harness detail metrics 的安全 allowlist；
- 不改变 evaluator authority 的 repair loop。

不要把 extractor 改成“帮 Agent 重新求解”，也不要将 private `gt.json`、`information.md`、
`tests/` 内容注入 subject。

### P1：统一 native loop / population / OpenEvolve 的反馈抽象

当前 Feature 052 只覆盖 effect-deep-trial 外层 loop。后续可以把 `RoundFeedback`、native
`ExecutionAwareRefinement`、population 的 best/novelty summary、OpenEvolve result envelope
统一到一个 runtime-neutral `EvolutionFeedback` 接口，但必须先有真实效果数据再抽象。

### P2：模型 profile 和成本控制

从知识库评测看，深度演化模型需要同时看质量、时延、token 和格式失败率。现有进度：

- Feature 054–057 已提供 `ModelProfile`、max steps/timeout、每次调用的 token/cost 预算和
  telemetry；深度试验的每个 fresh subject round 分别应用预算。
- Feature 059 补齐 missing usage、isolated 调用、显式 timeout 和精确预算耗尽时的行为。
- Feature 053 已提供 per-round error code/timeout breakdown；更细 parse failure 分类待需要时扩展。
- 跨所有 outer rounds 的总预算仍是后续工作；`thinking_budget` 当前只保存配置，未映射到
  provider 请求参数，不应声称它已经限制了推理 token。
- 后续支持新版 workload-based export 时，把权威 `experiment.request.workload_ref.kind` 纳入
  baseline adapter guard，并明确它与 `adapter_request.kind` 的优先级；
- best-of-run、best-of-round、suite average 的明确区分。

## 7. 6Astra 模型切换注意事项

截至交接时，仓库代码没有 `6Astra` 的硬编码限制。Lunar 的 OpenAI-compatible runtime 接受
任意非空模型字符串，入口包括：

```bash
--model 6Astra
--agent-runtime-model 6Astra
export FAMOU_MODEL=6Astra
```

但模型必须真实存在于所配置的 endpoint/provider，并且 provider 返回的 `model` 字段如果存在
必须满足身份校验。Codex Desktop 项目顶部的“当前模型”属于宿主应用的模型目录/权限选择，
不是 Lunar 仓库代码控制的配置；仓库无法把一个未被宿主暴露或未被 endpoint 支持的模型强行
加入 Codex 的模型切换列表。

后续接手者应区分两件事：

1. **Lunar CLI 调模型**：检查 `FAMOU_MODEL_ENDPOINT`、`FAMOU_MODEL` 或对应 CLI 参数，确认
   endpoint 的路由文档中确实使用 `6Astra` 这个精确 ID。
2. **Codex 项目本身切换模型**：检查 Codex Desktop 的宿主模型权限、项目策略和当前 host 的
   model catalog；这不由 Lunar 项目文件解决。

此问题在本次交接前尚未完成宿主侧诊断，不能把它误判成 Lunar runtime bug。

## 8. SDD 工作规范

当前 `.specify/feature.json` 指向：

```text
specs/097-benchmark-task-envelope
```

后续新功能必须：

1. 新建 `spec.md`、`plan.md`、`tasks.md`，必要时补 `research.md`、`data-model.md`、
   `quickstart.md`、`contracts/`。
2. 先写失败测试，再实现。
3. 运行：

```bash
uv run pytest -q
uv run ruff check src tests
uv run python -m compileall -q src
uv build
SPECIFY_FEATURE_DIRECTORY=/Users/liminghan/Documents/lunar_agent/specs/<feature> \
  bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```

4. 代码提交使用：`vchive <vchive@users.noreply.github.com>`。
5. 按当前范围直接在 `main` 开发并本地提交，不 push；不要擅自切换到工作树或新分支。

## 9. 接手第一步

新 Agent 应先阅读本文件、`README.md`、`docs/architecture.md`、Feature 051/052 的 SDD 文档，
然后执行：

```bash
cd /Users/liminghan/Documents/lunar_agent
git status --short --branch
git log --oneline -5
uv run pytest -q tests/test_effect_trial.py tests/test_deep_feedback.py tests/test_deep_effect_trial.py
```

接着阅读第 17 节并检查 GLM 实验的 started/report/diagnostics；当前 solver 是 `glm-5.1`。
复用冻结 suite 与 exact private harness，已有 GPT baseline 和第 15–16 节的 GPT 脚本仅用于
历史审计。不要重复运行 WebAgent、要求补数据或把 GLM 实评伪装成匹配模型的历史对照。
只有 exact harness 实际完成后才能报告新的独立分数；没有同模型 per-run baseline 时不计算
breakthrough，也不声称 WebAgent parity、suite parity 或 statistical superiority。

## 10. 本次续接记录（2026-09-06）

已通过 FM-Eval 官方只读 Query 取得 machine-readable 历史结果、case catalog 和 publication
身份，完成 `supply_chain_inventory` 的 official-publication kit、AgentServer normal-mode
baseline、provenance 和发布期 SDK 身份复算。历史三次分数为
`0.3496 / 0.3496 / 0.2415`；requested/effective model 都是 `gpt-5.6-sol`，evidence 为
`runtime_observed`，authority 为 `descriptive`，所选 case slice 的 conclusion eligibility 为
`eligible`。来源 adapter 是 `agentserver` 且 `deep_evolution=false`，因此不能把它标成 WebAgent
baseline。严格的 WebAgent comparison 仍缺同身份 `adapter=webagent` export。这些产物位于被
`.gitignore` 忽略的 `.lunar/famou-kit-real-001/`，不包含凭据。

本次还修复了普通/深度效果试验对未登记 record 的自动采信、深度 receipt/request 绑定、完整
telemetry/metric 恢复校验、未登记 harness 重评分、失败 attempt 复用边界、subject 越界创建
harness workspace、祖先 symlink、record/state 提交窗口，以及非 WebAgent baseline export 的
误接收。`record.previous.json` 只在摘要与 state 当前授权版本精确匹配时用于恢复；伪造或摘要
不匹配的 journal 会 fail closed。旧的已完成 schema 继续兼容读取，但不能追溯获得新摘要提供
的完整性保证；需要新证据时必须重新评分。

针对性及全仓测试、Ruff、compileall、构建、Feature 048/051 Specify 前置检查和
`git diff --check` 已通过。真实 `2 × 5` 深度试验尚未运行：当前环境缺少显式 subject endpoint/
model 凭据、extractor 的 `glm-5.2` 配置和包含 `anyio`、发布期 `claude_agent_sdk` 的运行环境。
不得把 AgentServer historical baseline 的准备完成误报为 WebAgent baseline 或新的 Lunar
效果结论。

Feature 054/055 已完成并通过全量 pytest、Ruff、compileall、构建、Specify prerequisites 和
`git diff --check`。Feature 056 已完成并通过全量 pytest、Ruff、compileall、构建、Specify
prerequisites 和 `git diff --check`，提交于 `8c00edd`。

## 11. Feature 057（2026-09-07）

Feature 057 已完成实现：`effect-subject` 支持受限 `ModelProfile`，并在不暴露凭据或分数的
前提下输出 profile digest、token usage 和 cost telemetry。普通/深度 effect trial 的请求、
receipt、logical record、report 和 resume identity 均绑定 profile digest；profile 文件被修改、
缺失或与请求模型不一致时 fail closed。无 profile 的旧请求和历史 record 继续兼容读取。

已通过全量 pytest、Ruff、compileall、`uv build`、Feature 057 Specify prerequisites 和
`git diff --check`，提交于 `9e08129`。真实效果试验仍未运行，subject endpoint/model 凭据及
exact extractor 运行环境待配置；不得据此声称 WebAgent parity 或新的效果结论。

## 12. Feature 058（2026-09-08）

Feature 058 已完成实现：新增只读 `effect-preflight`，在不启动 subject、exact harness 或
模型请求的情况下，复核冻结 suite/baseline、public case、命令可执行文件、显式环境变量、
model profile digest，以及 exact harness Python 的 import/distribution 能力。预检报告只保留
身份、哈希、版本和环境变量名称，不写入凭据、私有路径、命令原文、分数或 extractor/evaluator
输出；可选 JSON 文件使用新路径原子写入并拒绝 symlink/覆盖。

Feature 058 的聚焦测试和全量 pytest、Ruff、compileall、`uv build`、Feature 058 Specify
prerequisites 以及 `git diff --check` 均已通过。已从本地 raw export 生成带 `agentserver` 来源的
`baseline-agentserver.json`，历史最佳仍为 `0.3496`，仅用于所选 case 的描述性历史对照。
本轮没有运行 WebAgent 或真实 Lunar trial。未来真实试验需要显式 subject endpoint/model
凭据，以及包含 `anyio` 和发布期 `claude_agent_sdk==0.1.81`、并配置 `ANTHROPIC_MODEL=glm-5.2`
的 exact harness 环境。预检通过也不构成新的 Lunar 效果结论。

## 13. Feature 059（2026-09-08）

Feature 059 统一 `AgentLoopRuntime.run` 和 `run_isolated` 的模型执行约束。有 token/cost
上限时，每个返回的响应必须具备合法 usage；缺失、格式错误或超限会在执行工具、保存成功
响应或生成 subject completed receipt 前失败。用量刚好达到上限的最终文本可成功；同样
用量的工具请求会在副作用发生前停止，不再发起下一次模型调用。

显式 timeout 只能收紧 profile 上限。模型返回和各工具执行前后检查剩余时间，过期响应
不得成为成功结果或触发下一步。账本改为每次调用独立；isolated 仍只有 system/user 输入、
空工具集，不读写 transcript/memory，无 profile 的旧路径保持兼容。

先验证 69 项新增 runtime 回归中 42 项失败、27 项通过，及 4 项 subject adapter 回归全部
失败，再实现修复；实现后 126 项聚焦测试通过。费用依据响应后 usage 计算，不能撤销已计费
请求或保证单次请求绝不超支；运行中的模型/工具仍负责自身取消。跨整个深度试验的总预算
尚未实现，当前预算粒度是一轮 fresh subject invocation。

全仓 532 项 pytest、Ruff、compileall、`uv build`、Feature 059 Specify prerequisites 和
`git diff --check` 均通过；独立审查未发现阻塞问题。

继续使用已有 `baseline-agentserver.json`，不重新运行 WebAgent，也不要求新的平台实验数据。
后续优先按实际需求完善求解产物和演化流程；不在没有真实效果证据时抽象统一反馈接口。

## 14. Feature 060（2026-09-08）

已修复自定义 acceptance 的 `any` 分支可以绕过必需 OutputSpec 的问题。此前，缺少字段的
CSV 可能因为另一条文字条件通过而被提升并交付；现在声明输出始终与 base evaluator、task
acceptance 共同作为必过条件。删除了仅因 output_valid 出现在规则树中就跳过校验的优化。

`evaluate_output_contract` 复用既有格式、字段、大小与安全路径检查，独立处理最多 32 个
OutputSpec，并保留 `output_valid` 叶子诊断用于重试反馈。可选输出只有真正缺省才跳过；
已存在的目录、直接/断开/循环软链接、软链接祖先和非目录祖先都不能被当作缺省。
普通/委派 Solver、ContractCandidateRunner、最终 materialization 均使用该函数。

先确认 controller 17 项新增回归中 9 项失败、8 项通过，候选/最终产物的 4 项路径阻塞回归
全部失败；实现后 93 项聚焦测试通过。测试覆盖缺字段后重试修复、只提升正确产物并校验
交付摘要。旧 materialization 恢复证据无需迁移，但本次不会追溯重新评价已完成的历史 run。

现有通用 acceptance 语法仍保留自身 32-rule 上限；独立输出检查不消耗该表达式的规则额度。
本轮没有改变 CSV/JSON 内容格式规则、promotion 事务或 evaluator 评分权威。继续使用既有
实验数据，没有运行 WebAgent、真实 Lunar trial、平台查询或新的模型调用。

全仓 566 项 pytest、Ruff、compileall、`uv build`、Feature 060 Specify prerequisites 和
`git diff --check` 均通过；独立审查未发现阻塞问题。

## 15. 首次真实评测准备（2026-09-08）

用户要求继续并追问何时真实评测 Lunar。当前优先执行真实试验；无需等待下一项 feature，
也不再寻找 WebAgent 基线。首轮为 `supply_chain_inventory` 的 1 run × 1 round，通过后在
新 workspace 扩展为 2 runs × 5 rounds。沿用既有 company-platform/AgentServer baseline，
历史最佳 `0.3496`，保持单 case 描述性对照的证据边界。

本机准备产物（全部位于忽略目录，无凭据）：

```text
.lunar/real-eval-20260908/README.md
.lunar/real-eval-20260908/run.sh
.lunar/real-eval-20260908/input-checks.json
.lunar/real-eval-20260908/harness-environment.json
.lunar/real-eval-20260908/harness-requirements.lock
.lunar/real-eval-20260908/sdk-wheel-verification.json
.lunar/real-eval-20260908/readiness.json
.lunar/harness-venv-sdk-0.1.81/
```

准备结果：

- suite、baseline、raw export、完整 private case、extractor、evaluator 和公开文件摘要均
  已复核，baseline 的 benchmark/evaluation profile 与 suite 一致。
- 专用 Python `3.13.12` 使用 `venv --copies` 创建，可执行文件非 symlink。已安装
  `claude-agent-sdk==0.1.81`、`anyio==4.15.1`、`mcp==2.2.0`；extractor 所需 SDK 符号实际
  import 和 `pip check` 均通过。发布期仅锁定 SDK，传递依赖没有完整历史锁；本次实际版本
  单独记录，不能声称重建了发布期的完整依赖环境。
- PyPI 直连下载较慢，改用清华镜像获取 macOS arm64 SDK wheel，并核对官方 PyPI SHA-256：
  `e4bc8797cc2bc882031cf6b287a550ae2bb38a3822aa081e9ffc81bb4bed51da`。
- 启动脚本固定 subject `gpt-5.6-sol`、extractor `glm-5.2`，分别显式传递环境。每次先预检，
  通过后才启动 trial；拒绝缺失或空的四个连接变量。Bash 3.2 语法检查及缺省/空值退出检查
  通过，未创建 smoke/deep trial 目录。

本节准备阶段的启动阻塞曾是缺少以下连接配置，现已通过第 16 节的用户授权 CC Switch 接入解决：

```text
FAMOU_MODEL_ENDPOINT
FAMOU_API_KEY
ANTHROPIC_BASE_URL
ANTHROPIC_AUTH_TOKEN
```

已向用户请求现有环境配置文件路径或本机环境注入，不要求在聊天中发送密钥。不要搜索其他
应用的登录态来代替配置。配置到位后在同一进程环境中执行：

```bash
bash /Users/liminghan/Documents/lunar_agent/.lunar/real-eval-20260908/run.sh smoke
# 首轮真实链路完成并核对后：
bash /Users/liminghan/Documents/lunar_agent/.lunar/real-eval-20260908/run.sh deep
```

`run.sh` 每次都会重新预检；`smoke --resume` 或 `deep --resume` 只恢复各自冻结的配置。
当时 `readiness.json` 是缺配置状态记录，没有模型调用、私有 harness 执行或新的 Lunar 分数；
该文件现已更新为第 16 节的实际运行状态。本次准备仅更新交接文档和本地实验文件，没有修改产品实现，未重跑
已通过的 566 项全仓测试。

## 16. CC Switch 接入与首轮真实结果（2026-09-08）

用户明确授权使用本机 CC Switch，若不能接入再提供 key。已只读接入 CC Switch `3.19.2`
的当前 Codex/Claude provider；没有修改 app 设置或开启代理。辅助脚本
`.lunar/real-eval-20260908/ccswitch.py` 只读 settings 与 SQLite，将 API 配置仅通过进程环境
交给现有 `run.sh`，不输出或复制密钥。CC Switch 当前 Codex 默认模型虽然是 `gpt-6-astra`，
本次实验仍固定为 `gpt-5.6-sol`，未改变历史比较的模型名。

实际连接证据：

- 两组当前接口的模型列表都包含 `gpt-5.6-sol` 和 `glm-5.2`。
- 现有 Lunar Chat Completions runtime 的最小工具往返通过，两次响应均报告
  `gpt-5.6-sol`，探测共 205 tokens；没有执行本地工具。
- SDK `0.1.81` 在隔离临时目录用 `glm-5.2` 完成一轮无工具 query，报告模型相符。
- 完整 `effect-preflight` 通过，见 `ccswitch-preflight.json`。

首轮真实结果位于 `.lunar/real-eval-20260908/smoke/`：

| 项目 | 结果 |
| --- | --- |
| case / 配置 | supply_chain_inventory / 1 run × 1 round |
| 模式 | deep_evolution / loop 的第一轮 |
| overall / quality | 0.2079 |
| validity | 1.0 |
| 历史最佳 / 差值 | 0.3496 / −0.1417 |
| 用时 | 351.715 秒 |
| Lunar 模型交互 | 15 次 |
| Lunar 输入 / 输出 / 总 token | 95,723 / 4,383 / 100,106 |
| 实际响应模型 | gpt-5.6-sol，provider_observed |

首轮真实求解、原始私有 extractor/evaluator 和 receipt 链已完成；没有超越历史最佳。
独立只读审计 16 项证据一致性通过，包括 state 授权 record 摘要、request/receipt、公开输入、
solution manifest、实际 private case 和评分脚本摘要。`smoke --resume` 快速完成且返回报告
与原报告完全相同，没有新建 attempt。

这些用量仅属于 Lunar subject，不包括 extractor；harness receipt 未保存实评 extractor
的返回模型、usage 或完整成本。归一化中间文件和 SDK transcript 仍是临时产物，因此保留
证据支持 receipt 一致性审计，不能仅凭该目录离线重算评分。比较仍仅为本 case 的描述性
对照，baseline 的模型身份仅有 `runtime_observed`，不能升级为两侧 provider 证明。

后续独立 `deep/` workspace 的 2 runs × 5 rounds 已实际执行并结束，运行命令为：

```bash
uv run python .lunar/real-eval-20260908/ccswitch.py deep
```

两次逻辑 run 都在首轮 subject 以 `process_nonzero_exit` 退出，分别耗时 495.668 秒和
75.177 秒；没有 subject receipt/harness workspace，没有完成评分的 round，`lunar_best`
为 null。不能将这两次失败解释为质量分 0 或零模型消耗。首轮 smoke 的独立结果仍有效，
但本次没有得到演化提升证据。

事后纯本地复核发现 run 1 的原始公开文件未变，但新增了 `subject/case/solve.py`，违反
冻结 public projection 的文件集合；run 2 的同项检查通过。新增文件若走后验校验必被拒绝，
但由于检查在 `agent.run()` 返回后，无法仅凭当前文件断言它就是历史退出的直接原因。
失败后再次极小模型请求成功，响应仍为 `gpt-5.6-sol`；这只证明当前连接可用，不能排除
历史瞬时接口故障。独立只读审查确认以上证据边界。

当前诊断缺口已由真实失败暴露：`effect_trial._default_executor` 将 stdout/stderr 送入
DEVNULL，`_invoke` 统一记录 `process_nonzero_exit`，`run_subject_adapter` 又将 runtime
异常压成类型名。下一项 SDD 应补充 score-free、有界、白名单字段的 subject 失败诊断，
保存失败阶段/安全错误类别/退出状态；不要直接保存可能包含凭据的原始 stdout/stderr。
同时明确整个 `case/` 目录不可新增文件，求解代码和产物写在 attempt 根目录或其他允许目录。
先用本地回归区分 public projection 与 runtime/模型失败，再修复并恢复真实试验；保留原始
失败 attempts，不盲目重复消耗调用。此轮没有修改产品实现，仍以 `790c086` 对应实现开展
试验；新增内容仅是本机接入/状态脚本、结果记录和本文档。

汇总说明位于 `.lunar/real-eval-20260908/results.md`。每次新启动/恢复会读取届时 CC Switch
的当前 provider；已经运行的进程环境不受之后全局切换影响。新结果只从实际登记的 round
及最终 report 派生，不改基线、不手填分数、不向 subject 提供私有评分内容。

## 17. WebAgent 记录模型与 GLM 实评（2026-09-08）

用户明确要求“别用这么好的模型，用 WebAgent 已有记录的模型”。选择 `glm-5.1`：离线
报告 `qx9kRYpa6zTQmP` 的 C/E 组明确记载 `webagent loop / glm-5.1`。报告属于 20 case、
12 小时、每组 3 次的聚合实验，不能作为当前单 case 的同模型 baseline。无需再运行 WebAgent、
索取新实验数据或修改已有 GPT baseline。旧 `ccswitch.py smoke/deep` 与 `run.sh` 固定 GPT，
保留供审计，后续不得误用它们启动新的求解。

经用户授权继续只读使用本机 CC Switch。虽然当前 provider 的模型列表没有列出 `glm-5.1`，
实际文本调用与两轮 function-call probe 都成功，响应模型均为 `glm-5.1`；工具探测共 403
tokens。冻结 extractor 仍为 `glm-5.2`，SDK 仍为 `claude-agent-sdk==0.1.81`。

本机忽略目录 `.lunar/real-eval-glm-5.1-20260908/` 保存连接证据、模型选择、profile、冻结
suite、单 case 请求和 `run_single.py`。该脚本只导入旧 CC Switch 脚本的环境加载函数，
不会调用旧 GPT 启动入口。新求解预算为 40 个工具 steps、900 秒、200,000 tokens；无已核实单价，
不编造美元成本或设置虚假的费用估计。Profile canonical SHA-256：
`b2589138335badc4b9ff0fbb27f20f4235b397844e65e122b54b9150d9e587fc`。

现有 `EffectTrialRunner` 要求 requested model 与 baseline model 一致，本次保留该 guard。
独立实评调用现有 `effect-subject` 与 exact `effect-harness`，报告标注
`kind=lunar_single_case_evaluation`、`comparisons_disabled=true`、
`same_model_baseline_available=false`；不是普通/深度 comparative trial 的替代 schema。
subject 成功后才运行原始私有 extractor/evaluator，分数只取自其实际 receipt。

实际 GLM 运行已结束：subject 耗时 900.333 秒、退出码 2，总用时 900.334 秒。
规范诊断为 `stage=model`、`code=timeout`、`http_status=null`，记录到 12 次模型响应事件、
13 次工具结果事件。工具计数包含失败结果的可能性，不能说 13 次工具操作均成功。
没有候选文件、成功 subject receipt 或 harness 目录，0 次评分；质量分未知，不能记为 0。
失败调用用量与返回模型链不完整；连接探测确认同名模型，但不能据此补造本次运行的
provider_observed 成功回执、token 数或费用。

事后复核 request/public projection、sidecar 与采集副本、启动时所有产品 Python 源文件
SHA 均一致，原 GPT baseline 未改动。工具执行已开启，最小环境中的 `python3` 可正常
启动；没有证据断言具体工具错误、provider 断线或某次读取导致了超时。过程不保存原始
模型/工具正文，因此不能重建前 13 次工具操作。结果与本地核验分别在 `results.md`、
`report.json`、`postmortem-checks.json`；`started.json` 拒绝对已启动目录重复执行。

2026-09-09 用户纠正了此前“先取得正常解”的优先级：未产生正常解可能是合理的测量结果，
应结合已有真实评测数据判断。当前目标改为在明确、冻结的预算下测量 Lunar 的完成率、
有效解比例和质量，允许失败成为正式样本；不以取得成功为停止条件。下一批应预先冻结
配置与尝试次数，同时保留全部成功/失败；把进程完成、extractor 完成、evaluator validity、
质量分与用量分别统计。变更 prompt、工具能力或预算时，另立明确的变体和假设，不把“不断
重跑直到成功”的 best result 代替总体表现。只对确定性复现的缺陷做修复；早落盘、预算提示
和更长 timeout 目前都只是待验证假设。本轮已完成两次预先冻结的新 attempt，结果见第 20 节。

## 19. 按真实历史数据解释无解（2026-09-09）

重新复核已有离线报告 `qx9kRYpa6zTQmP`，其中 `webagent loop / glm-5.1` 的 C 组有效解
比例为 57.9%，E 组为 93.0%；表中平均分分别为 0.478、0.854。这个数据证明 WebAgent
也并非始终取得有效解。报告没有提供该指标的超时、运行错误或格式错误细分，不能把有效解
比例的补数称作超时率，也不能推断当前 `supply_chain_inventory` 的失败概率或历史结果。

两组均为 20 case、每组 3 次取平均、12 小时演化，并从 agent build 产物开始；E 组还在
演化期间使用真值评估器。单解“评估”上限为 10800 秒，不等同于 subject 求解预算。
Lunar 本次是从公开输入冷启动的 normal subject，整轮预算为 900 秒，harness 尚未运行。
因此既不能拿 57.9%/93.0% 作为当前单 case 的匹配成功率，也不能通过简单时长比例推定
Lunar 应有表现；尤其不能为了贴近 E 组而把私有评估器内容交给 subject。

本次应记为一个在指定预算内未完成的真实样本，尚无证据表明它是实现缺陷、模型不可用或
框架劣势。无解不写成成功，也不当成质量零分或代码 bug。结构化复核在本机
`.lunar/real-eval-glm-5.1-20260908/historical-context.json`。

## 20. 两槽固定预算测量结果（2026-09-09）

为避免“重跑到成功”，新建了独立 campaign
`.lunar/real-eval-glm-5.1-20260909/`，预先冻结两个 normal slot：同一
`glm-5.1`、profile、公开 case、prompt/adapter、40 tool steps、900 秒和 200,000 token ceiling。
2026-09-08 的单次 exploratory pilot 不进入这两个 slot 的分母。两个 slot 并行执行，使用同一
授权 provider 配置；并发限制已写入 summary，不能把它们解释为完全独立的时序重复。

两个 slot 均在 subject 阶段退出码 2，耗时分别约 310.289 秒和 250.987 秒；Feature 061
诊断均为 `stage=runtime`、`code=budget_exceeded`，各观察到 14 次模型响应事件和 15 次工具
结果事件。这个诊断不说明具体是哪次工具、是否为 provider 故障或是否触发 token ceiling。
两个 slot 都没有 subject receipt、候选文件、harness 目录或评分。

固定分母汇总为：planned 2、terminated 2、process success 0、subject receipt 0、harness
started 0、scored 0、valid 0、failed 2、unresolved 0；`valid_solution_rate=0/2` 是完成率
统计，不是质量分 0。overall/quality 的 `n=0` 且值为 null，usage known 为 0，不能声称
token 消耗或费用为零。结构化汇总为
`.lunar/real-eval-glm-5.1-20260909/summary.json`。

这批结果仍不能证明 Lunar 框架劣势：样本只有两个、subject 是冷启动、历史 WebAgent
实验条件不同，而且本次没有进入 evaluator。后续若继续，应先重新冻结新的变体和样本数；
不能在同一 campaign 中改 prompt、预算、工具后补位，也不能把成功样本挑出来替代失败样本。

## 18. Feature 061 安全失败诊断（2026-09-08）

新增 4096 字节上限的严格 score-free sidecar，绑定执行前 request SHA、normal/deep 模式、
run/round，保留固定阶段/错误码、有限模型/工具计数和可选 HTTP 整数。normal/deep runner
只在 subject 失败时验证并采集到 attempt 的 `diagnostics/`；缺失、伪造、超大、陈旧、
symlink/FIFO/其他不安全文件均不改变原 process 错误。分类或发布自身失败也保留原异常。
没有保存原始 stdout/stderr、异常正文、模型/工具内容或密钥；评分、成功 receipt、记录与
resume schema 保持兼容。两种 subject prompt 明确整个 `case/` 树不可新增、修改或删除。

原始 HEAD 上新增 9 项回归全部先失败；最终全仓 634 项测试、Ruff、compileall、build、
Feature 061 Specify prerequisites、diff 检查通过。独立代码审查无阻塞问题；真实 GLM
超时也成功生成并采集规范诊断。诊断不保存完整失败用量，计数只代表可观测事件。

## 21. WebAgent 分支审查与 Feature 063（2026-09-09）

已 fetch WebAgent，`famou-v2.5/base` 从 `465af9d` 更新至当天 `e24df25`。盘点全部远端分支，
深入检查 base、memory_card `865a270`、layered-compaction `5197081` 及演化/角色分支。
完整结论见 [分支审查文档](docs/webagent-v25-review-20260909.md)。

本轮实际移植为 Feature 063：从 v2.5 的参数说明丢失修复吸收“验证最终模型请求”的原则。
Lunar 不使用 Zod，只在既有 `LocalToolRegistry` schema 上补齐参数描述：工作区路径、
有界文件预览、完整覆盖写入、无 shell argv、实际单命令 timeout、用户问题限制、记忆作用域。
没有改变执行参数、权限、工具开关、评分或恢复 schema。明确 `read_file` 没有分页，且
旧实现截断 UTF-8 字符时可能解码失败；后续可在分页功能中单独复现和修复。

4 项 provider HTTP 边界回归在旧实现全部失败；实现后 40 项聚焦测试和 638 项全仓测试通过，
Ruff、compileall、build、Specify 和 diff 检查通过。测试覆盖 command/memory 四种开关组合
与最终请求中的描述；随后用非默认 timeout/output limit 检查实际配置文案。独立审查未发现
阻断问题。本轮模型响应来自本地 HTTP fixture，没有真实模型调用或新评分。

下一步优先做整轮/单命令预算及增量 checkpoint 的 SDD。普通 registry 默认 30 秒，但 effect
subject 实际是最多 300 秒，不能把 WebAgent skill 的固定 10 秒余量照搬。Lunar 命令结果
当前非流式，也不保证 SIGTERM 宽限。checkpoint 不等于成功 receipt，更不能自动补分。
上下文压缩、稳定 project memory scope 和输出尾部预览有价值，分别按后续需求设计。
WebAgent LC 的原生工具配对和迁移后测试尚不充分；result store 注释的不可覆盖也不是其
普通 writeFile 的文件系统保证。不要照搬这些实现或把分支设计表述成已验证效果。

Feature 063 改变了模型可见上下文，未来实评必须新建并冻结变体、attempt 数和统计口径。
仍使用用户选定的 `glm-5.1` 和现有 exact harness；已记录的失败不补位、不改成零质量分。

## 22. Feature 064 预算感知与候选保存（2026-09-09）

`AgentLoopRuntime.run` 使用 model profile 时，每次模型请求会在复制的 system 消息里生成
当前预算提示：本轮剩余秒数、可用工具调用数、已配置的累计 token/cost 余量，以及当时可用
的单命令上限。未配置的花费上限和未开放的命令分别为 null，不编造缺失 usage 或价格。
提示不追加进历史、transcript 或 memory；isolated 和无 profile 的模型上下文保持原样。

命令执行通过 context-local deadline scope 使用本轮绝对 monotonic 截止时间，每次启动前
重新计算 `min(command_timeout, remaining)`；嵌套只能收紧，异常退出恢复，不改 registry
本身的固定 timeout，保留旧 execute 三参数接口。全局调用仍有原来的前后 profile 检查。
这属于协作式 timeout，不保证进程树取消、SIGTERM 宽限、流式输出或精确墙钟强制中止。

共同的 `write_file` 改为同目录唯一临时文件 → 完整写入/flush/fsync → 原子替换。失败时
保留旧候选且不报告 artifact，尽力清理临时文件；强制杀进程可能留下未登记临时文件。
已有文件保留权限，新文件为 0600；原子替换只改变该路径，其他硬链接仍指向旧内容。
这不是自动多文件 checkpoint，生成的长脚本仍须主动实现自己的增量保存。

同时本地确定性复现并修复 `_run_command` 的超时输出类型 bug：TimeoutExpired 中只有
stdout 或 stderr 为 bytes 时，原本与空字符串拼接产生 TypeError，丢掉已有输出；现在
先分别解码再组合，仍返回失败工具结果。没有扩张 Feature 061 sidecar 保存内容，既有
字符计数截断器、read_file 分页/UTF-8 截断问题本轮没有修改。

失败测试先验证 12 项预算/命令测试中 10 失败、2 通过；首批 8 项原子写测试中 5 失败、
3 通过；2 项普通 profile HTTP 测试在提示缺失时失败，4 项兼容用例通过。另补 2 项部分
写入中断测试及 1 项端到端失败候选测试，共新增 29 项。170 项聚焦测试及全仓 667 项测试
通过，Ruff、compileall、build、Specify 和 diff 检查通过；独立审查无阻断问题。

端到端 fixture 在第二次模型响应累计 token 超限前已保存候选和摘要，验证文件保留、
subject receipt 缺失、harness 未调用、逻辑 run 失败、分数/usage 为 null，诊断仍为
runtime/budget_exceeded。所有模型返回来自本机 HTTP fixture，没有外部模型调用、WebAgent
执行、公司平台查询或新真实评分。2026-09-08/09 的 campaign 和统计分母保持不变。

## 23. Feature 065：预算感知变体真实测量（2026-09-09）

预注册提交 `cb590aa`，产品实现 `6189e50`。新 campaign 为
`.lunar/real-eval-glm-5.1-variant-v2-20260909/`，在两个全新兄弟 attempt 目录各启动一次。
保持之前的 parallel=2、`glm-5.1`、40 tool calls、900 秒与 200,000 token ceiling；suite/
公开文件、private case/harness、SDK 0.1.81 和 extractor `glm-5.2` 均保持相同。runner
改为共享一次 CC Switch 环境快照，启动前核对冻结源码和输入；没有新模型连接探测或补跑。
manifest 不随状态更新，观测写到独立 started/terminated/report 文件。

| 项目 | Slot 1 | Slot 2 |
| --- | --- | --- |
| subject 耗时 | 299.895 秒 | 264.173 秒 |
| subject 退出码 | 2 | 2 |
| 诊断 | runtime/budget_exceeded | runtime/budget_exceeded |
| 模型响应/工具结果事件 | 11 / 12 | 13 / 14 |
| 新增文件 / 成功 receipt | 0 / 无 | 0 / 无 |
| harness / 分数 | 未运行 / null | 未运行 / null |

两次失败均占槽，planned=2、failed=2、valid=0、scored=0、unresolved=0。`valid_solution_rate`
为 0/2，表示完成率统计；overall/quality n=0 且值为 null。失败完整 usage 与费用未知，
不能当作零，也不能将事件次数换算成 token 消耗。本次无需也没有运行 extractor/evaluator。

独立离线审计通过：35 个源码文件、14 个冻结输入、57 个历史证据文件、22 个观测 SHA
链均一致；public projection、private case/harness 和历史 campaign 未变。最终进程检查
未发现本批 runner/subject/harness 残留。原产品 667 项测试已于 Feature 064 通过，本轮
没有改产品代码，执行了本机脚本语法、只读预检、Specify 和 diff 检查。

预注册 manifest SHA：`7bc9df8abb895312a24d707afcd8aa708642472a3d9dd1515ad83c738e0abe7b`。
summary SHA：`7dec7eef0b97bba8547c1ef44535259f648439a4a4884f9991311d22f5db9c9a`。
完整说明、机器汇总与审计分别为该 campaign 的 `results.md`、`summary.json`、`audit.json`；
`summarize.py --check-only` 可离线复核，`run_campaign.py` 已有 started marker，不能重启。

本批没有观察到新工具说明和预算提示改善完成率。这只有两个并发样本，包含多个改动，
且没有进入 evaluator，不能推出整体框架劣势、某项改动无效或已定位 provider 故障。
前批 0/2 与本批 0/2 是两个独立配置的分母，不合并、不挑成功、不重跑到成功为止。

## 24. Feature 066：有界预算失败证据（2026-09-09）

UsageLedger 在 token/cost 超限前生成不可变 accepted/observed 快照，经专用异常传到
AgentLoop 和 subject observer。超限仍拒绝入账，observed 包含触发响应；恰好达到上限
的工具响应已入账但停止执行，两个快照相同。最终文本恰好上限仍允许成功。原先 token
优先顺序、累计费用分方向向上取整、账本提交时机和模型/工具事件计数均保持。

仅类型化预算失败发 sidecar v2：保留原 v1 字段，新增严格 budget 对象，记录 limit、state、
maximum、accepted_usage、observed_usage、trigger_recorded 和固定 usage_completeness=partial。
每个快照含 input/output/total tokens、可选 profile cost_micros 与 rounds。数值上限为
10^15，rounds 为 10^6；无法表示的上限或整份快照为 null，不裁剪成伪精确数字，也不限制
运行时原有整数算术。费用是配置价格的推算，不是 provider 账单；部分响应观测不是完整
失败用量。缺失/无效 usage 不生成预算数值，异常文本与任意附加属性不能冒充类型化证据。

v1 继续严格读取、原样采集，其他失败继续使用 v1。v2 校验精确字段、整数范围、累计关系、
触发状态及上限关系，沿用 4096 bytes、安全排他发布和执行前身份绑定。非权威诊断不改变
process 失败、receipt、harness、score、resume 或 promotion。normal 本机 HTTP 回归验证
候选保留但没有 receipt/harness/评分，完整 usage/cost 仍为 null；deep 验证第二轮失败
仍保留前轮分数，恢复使用新 attempt，旧诊断字节不变。

失败先行：首批诊断测试 10 failed / 36 passed，账本新增测试 5 failed / 11 passed，
集成目标 2 failed / 1 passed。最后共新增 59 项用例，全仓 726 passed（30.35 秒），
Ruff、compileall、build、Feature 066 Specify 和 diff 检查通过；独立审查无阻断问题，
另跑相关 229 项测试通过。规格、方案和验收见 `specs/066-budget-failure-evidence/`。

本轮没有真实模型调用、WebAgent 执行、公司平台查询或历史结果回填。没有新的测量结论，
Feature 065 的 0/2 与 null 分数仍原样保留。旧 campaign 的源码 SHA 审计针对其冻结版本，
当前实现已经变化，不能为通过旧脚本的当前源码检查而改写 manifest 或历史 summary。

## 25. Feature 067：新诊断真实测量与 token 触发证据（2026-09-09）

预注册提交 `9c00b88`，产品源码 `01c541e`；新 campaign 为
`.lunar/real-eval-glm-5.1-budget-diagnostics-20260909/`，两次独立 normal attempt 在全新
兄弟目录各启动一次、共享一次 CC Switch 环境快照并行执行。与 Feature 065 相比仅源码
诊断变化，prompt/工具行为、glm-5.1、40 tool calls、900 秒、200000 tokens、公开输入、
private case/harness、SDK 0.1.81 与 extractor glm-5.2 保持相同；没有连接探测或补位。

| 观测 | Slot 1 | Slot 2 |
| --- | ---: | ---: |
| Subject 耗时（秒）/ 退出码 | 488.371 / 2 | 522.781 / 2 |
| 明确触发项 / 状态 | max_total_tokens / exceeded | max_total_tokens / exceeded |
| 已接受累计 input / output | 159471 / 20096 | 184628 / 13492 |
| 已接受累计 total / rounds | 179567 / 11 | 198120 / 12 |
| 含触发响应累计 input / output | 185141 / 29582 | 210116 / 28596 |
| 含触发响应累计 total / rounds | 214723 / 12 | 238712 / 13 |
| 触发前剩余 tokens | 20433 | 1880 |
| 触发响应 input / output | 25670 / 9486 | 25488 / 15104 |
| 模型响应事件 / 工具结果事件 | 11 / 12 | 12 / 13 |
| 保留普通文件数 | 3 | 1 |
| Subject receipt / harness / 分数 | 无 / 未运行 / null | 无 / 未运行 / null |

两个触发响应都未入账（trigger_recorded=false），快照固定 usage_completeness=partial。
费用与完整失败用量仍未知，事件计数不包含触发失败的模型响应，不通过事件或差值补造
完整账单。Slot 1 保留 analyze.py、analyze2.py、analyze3.py；Slot 2 为 solve.py。
只检查文件名、类型和大小，未读取正文或另行执行，不能宣称已有有效候选或补跑评分。

固定分母 planned=2、started=2、terminated=2、failed=2、valid=0、scored=0、unresolved=0；
有效解比例 0/2。overall/quality n=0 且为 null；usage_known_attempts=0，total_tokens_known
为 null。两个 v2 budget diagnostics 单独计数，不混入完整 usage；历史分母和结果不变。

确定性事后算术显示：两个最后请求的 input tokens 已分别超出剩余额度 5237 / 23608，
尚未计入当轮 output。观测累计输入占比约 86.22% / 88.02%。这支持优先验证上下文输入
开销管理，但没有原始消息/工具正文，不能定位具体读取或证明归档/压缩必然有效；新增
文件和更长运行时间也不能归因于诊断功能。只确认本批 token 触发项，不回填以前失败。

独立预启动/最终审计通过：35 源码（与实现 git blob 相同）、14 输入、95 历史文件、
22 个观测 SHA 链及新版汇总一致；预注册提交先于启动。最终无本批进程残留。本轮产品
源码未改，沿用 Feature 066 的 726 项通过测试，执行了本机脚本语法、无调用 readiness、
预检、部分用量/旧版/未决汇总回归、Specify 与 diff 检查。

Manifest SHA：`41479e3b5d97ea3e2635aea0dc1ae831b18d15bbe746e0f002163826f8553e5f`。
Summary SHA：`7c90a35bf958306d6d030019093f42e2e4f0ea4f0d98bb6252e4af9fb30f05cb`。
Audit SHA：`1d19768cabe8d9e9cca229f19447894842e80f7cc1c69056425ebb68a5ac1674`。
完整结果、汇总、审计和派生算术分别位于本机 campaign 的 `results.md`、`summary.json`、
`audit.json`、`budget-analysis.json`。`summarize.py --check-only` 为只读复核；启动器有
started marker，不能再执行。未来代码变化不应导致改写本批 manifest 或历史源码锚点。
已完成：独立预启动审计通过，两个槽各启动一次。钣金案例约 49.1 分钟完成并评分
0.999999；邮政案例约 90 分钟仍未提交有效回执，最终按预注册超时失败保留。该结果
说明“WebAgent 高分 case”在 Lunar 充足预算下可以做出至少一个有效解，但不保证每个
case 都在一次 bounded run 内完成。旧 GLM-5.1 失败 campaign 未改写、不补跑。
