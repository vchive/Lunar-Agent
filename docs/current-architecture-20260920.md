# Lunar Agent：当前架构与执行链路

日期：2026-09-20。依据当前产品源码核对；产品基线为 `87d86d9`，不是未来设计图。

## 1. 系统定位

Lunar 是一个本地运行、持久保存状态的 Agent 执行系统，并带有原生程序演化引擎。它已经能把自然语言任务转成结构化合同，调用模型和工具生成产物，运行候选程序，独立检查结果，并把可核验的文件交给父任务。

系统目前是 **Python 模块化单体 + SQLite + 本地工作目录 + 受控子进程**。`lunar-agent` 和兼容命令 `famou` 都进入 `src/famou/cli.py`；`famou` 是仓库内部保留的包名。当前不依赖独立部署的调度服务、消息队列或全局 Hermes 环境。

这里有两种不同的循环：`AgentLoopRuntime` 是模型调用工具、读取反馈、继续工作的循环；`PopulationStrategy` 是生成多个程序、执行评分、选优再生成的演化循环。旧的 `LoopStrategy` 演化策略已经退役，不能和仍在使用的 Agent 工具循环混淆。

当前主要演化对象是任务的候选程序与解法。搜索会改变候选源码和候选集合，不会自动修改 Lunar 控制器本身，也不是在线训练模型权重。

| 运行方式 | 模型主要做什么 | 系统额外做什么 |
| --- | --- | --- |
| 普通 Agent 任务 | 根据计划工作，可调用工具完成当前任务 | 管理任务依赖、保存结果、按验收规则检查 |
| 原生演化任务 | 生成候选和改进候选，可在每次生成中使用工具 | 维护种群，运行程序，独立评分，选择和迭代 |
| 外部 producer | 由外部框架搜索并提交候选 | Lunar 对接收材料重新准入、评测和登记 |

因此“允许更多工具步骤”和“进行更多演化轮次”是两项不同的预算。前者帮助一次生成完成，后者扩大被验证的候选搜索范围。

## 2. 总体结构

```mermaid
flowchart TD
    U[用户目标、输入文件、运行配置] --> CLI[CLI 入口与参数检查]
    CLI --> C[LocalController：任务和运行编排]
    C <--> DB[(Store：SQLite 状态与事件)]
    C <--> F[工作目录、产物与恢复日志]
    C --> D[普通任务计划与依赖调度]
    D --> R[Runtime：单次调用或 Agent 工具循环]
    C --> E[演化任务：生成、执行、评分、选优]
    E --> A[AgentAdapter：角色与候选生成]
    A --> R
    R --> M[模型服务 / 显式子进程 / Mock]
    R --> T[本地工具]
    E --> X[候选执行器与独立评测器]
    D --> V[任务验收]
    X --> P[已验证产物交付]
    V --> P
    P --> F
```

普通任务调度直接通过 `Runtime` 协议调用运行时；显式角色委派及演化生成另有 `AgentAdapter` 通道。二者共用 Controller/Store 的状态管理。源码中没有独立的 scheduler 服务；调度循环在 `LocalController.resume()`，依赖推进和任务领取在 Store。

| 层 | 当前职责 | 主要实现 |
| --- | --- | --- |
| 入口与编排 | 命令、模式校验、输入导入、继续运行、普通/演化分流 | `cli.py` |
| 控制层 | 创建/领取任务、并发、预算检查、结果登记、取消、父子交付 | `controller.py` |
| 显式 worker 控制面 | 有 owner 的可恢复 worker session，等待、消息、取消、级联和重启 reconcile | `workers.py`、`store.py` |
| 状态层 | run/task/attempt、事件、产物索引、计划版本、进程归属 | `store.py`、`models.py` |
| 计划与角色 | 任务合同、依赖图、领域与能力选择、恢复建议 | `conversational.py`、`algorithm.py`、`policy.py`、`routing.py`、`profiles.py`、`recovery.py` |
| 模型与工具 | Mock、显式进程、兼容接口；工具循环、请求预算、会话 | `runtime.py`、`agents.py`、`agent_loop.py`、`tools.py`、`model_profile.py` |
| 演化搜索 | 种群、候选档案、生成与评估接口、选优与停止 | `evolution.py`、`agent_evolution.py` |
| 多文件程序 | 源码包、执行计划、输入、执行记录、评分快照、交付 | `candidate_*.py`、`bundle_*.py`、`automatic_solve_bundle.py` |
| 外部生产者 | 将外部候选转换成可由 Lunar 重新核验的输入 | `openevolve_handoff.py`、`shinka_handoff.py`、`producer_handoff.py`、`seed_handoff.py` |
| 验收工具 | 固定任务和预算、监控真实请求、只读检查与报告 | `specs/*/measurement/`，不属于日常产品运行的必经层 |

Feature 143 增加了一条与普通 task DAG 分开的显式 worker 链路：Controller 通过
`dispatch_worker/send_worker/list_workers/wait_worker/cancel_worker/resume_worker` 操作稳定的
worker identity，Store 保存 worker、attempt 和受限事件。worker 的 activity phase 与最近一次
outcome 分开记录；直接 owner 才能操作，父取消会传播到已验证的子树，进程重启时未完成运行
标记为 `lost`。结果默认内联截断，大结果写入 worker attempt 目录并由带 SHA-256 的引用读取。
这条链路复用现有 AgentAdapter，但尚未迁移普通 delegation，也没有改变 task DAG 或自动多文件
入口的生命周期。

## 3. 普通任务怎样执行

最常用的对话入口是 `solve`。没有启用演化时，执行顺序为：

1. 检查参数，创建父 run，将输入复制到 run 的 `data/raw` 并登记大小和 SHA-256；每个 attempt 执行前再核验并复制到自己的目录。
2. `RuntimeContractCompiler` 把目标转换为 `AlgorithmProblemContract`，明确输入、输出、约束和目标。如果关键信息不足，保存问题并进入 `awaiting_input`。
3. 根据合同创建默认依赖图：`data_discovery → formulate → solve → verify`。显式 `--role-dag` 使用更细的角色计划；角色不意味着系统自动配置了多家模型。
4. Controller 从 Store 领取依赖已满足的任务。默认一个 worker，配置并发后以独立运行时执行可并行任务。
5. Runtime 获得任务提示和工作目录。启用 Agent loop 后，模型可反复读文件、写文件、查看目录、询问用户；命令执行和记忆是显式能力选项。
6. 保存结果、会话和文件，运行当前任务的验收规则，再推进依赖或记录失败。允许的普通重试受配置限制。
7. 全部必需任务和产物满足条件后，由 Controller/Store 确定终态，用户可查看状态、事件和交付文件。

`run` 更直接地执行给定任务/计划，默认不会像 `solve` 那样先编译合同；`delegate` 通过角色能力注册表调用 Agent。普通对话任务在合同尚未生成时应走 `solve --resume --run-id` 或 `answer`，不能把裸 `resume` 当成所有合同编译场景的通用恢复入口。

普通任务的默认验收不是通用语义判题器：默认各领域 evaluator 都使用非空结果检查，显式 acceptance、角色证据、输出结构检查再增加约束，复杂问题仍需要合适的评测合同。普通 DAG 的前驱产物传递也没有像多文件执行证据链那样逐份重算所有前驱文件的指纹。

`MasterPolicy` 和 `DomainRouter` 当前是确定性的规则实现。`solve` 的合同来自模型，但默认任务图由程序构建；不能把当前系统描述成由一个大模型总管自由生成并管理任意 Agent 团队。合同编译优先走单轮 `run_isolated()`，不用候选生成时的工具循环、记忆或会话历史。

## 4. 原生自动多文件演化怎样执行

入口为 `solve --evolve --multi-file`。当前只接原生 population 策略，自动准备 evaluator；外部 producer 和后台模式尚未接到这个入口。

```mermaid
flowchart TD
    G[目标与输入] --> K[编译任务合同]
    K --> EC[生成 evaluator 与基础测试]
    EC --> AU[独立 auditor 提供检查用例]
    AU --> PF[本地预检、冻结 evaluator/profile]
    PF --> CH[建立父子任务关联]
    CH --> GEN[Agent 生成完整多文件候选]
    GEN --> PAR[严格解析、生成完成回执]
    PAR --> EX[复制输入、在独立目录执行候选]
    EX --> EV[对评测时输出快照独立评分]
    EV --> AR[候选档案、有效性优先选优]
    AR -->|尚有轮次和预算| GEN
    AR -->|已停止且有有效候选| OUT[向父任务交付源码、输出和证据]
```

这条链分成准备与搜索两段。准备通过后才创建和运行候选；搜索期间使用同一份冻结评测器。候选生成时，模型写过文件不代表候选已经完成：最终结构必须被解析器接受，并产生绑定 run、task、budget、candidate 和源码摘要的持久记录。

多文件候选经过源码包检查、工作目录与执行计划绑定、输入登记、候选程序执行、输出检查、独立 evaluator 运行，再进入候选档案。排名先看有效性，再看目标分数；配置启用时还包含种群多样性和岛间迁移等搜索控制。模型和外部生产者自报的分数都不能直接代替 Lunar 的最终评分。

多文件交付复制完整源码、输入与已评分输出快照、合同和评价材料，并以摘要关联原执行证据。绑定原工作区 inode 的 launch-intent/result/completed 记录保留在原处，不会搬到父交付包中。评测快照是在成功执行之后、独立评分时采集的，不是进程退出瞬间的输出证明。

该路径不再重跑被选中的候选来“证明”交付。旧单文件演化的 materialization 路径可能再次执行选中程序以生成最终输出，不能把两种交付语义混在一起。

所谓独立评测，是生成器、执行器和评分器职责分开、评分依赖实际文件；compiler 和 auditor 仍可能使用同一模型服务。auditor 看得到 evaluator 源码，但看不到 compiler 的自测探针；solver 不接收 evaluator 实现和两组探针。它提高可检查性，不保证生成的 evaluator 对任意新任务都正确。预检、审计用例和真实留出测试用于进一步验证它；真实 holdout 属于独立验收工具，不是每次日常 solve 默认必跑的阶段。

## 5. 状态、文件和恢复如何衔接

| 对象 | 含义与作用 |
| --- | --- |
| `Run` | 一次持久任务，记录整体状态、工作目录、计划、预算和后台进程 |
| `Task` | run 内可调度的工作单元，带依赖、验收规则、输入问题和结果路径 |
| `Attempt` | 一个 task 的一次执行，记录运行时、进程、开始/结束和错误 |
| `PlanDocument` | 有版本的任务图和问题合同，调整计划需留下版本与事件 |
| `Artifact` | 产物文件的路径、大小、内容摘要和归属 |
| `Candidate / Receipt` | 候选源码与生成、执行、评价身份的绑定关系 |
| `CandidateArchive` | 候选、评分、状态与演化结果的持久档案 |
| 发布日志 | 在文件发布与数据库登记之间留下可核验的阶段，支持有条件恢复 |

默认配置仍保留 `.famou` / `FAMOU_HOME` 兼容名称；显式 `--home` 可使用 `.lunar` 或其他目录。`state.db` 使用 SQLite WAL，保存调度权威与事件；大块源码、输入、输出、模型会话和执行证据放在工作目录。

任务的 `waiting` 可以表示等前驱依赖，也可以表示等用户；只有带真实非空问题的任务才对应用户待答。`answer` 把答案保存为产物并恢复原 run/task，不会把依赖等待误当作用户问题。

在演化执行与交付证据链中，恢复先检查登记状态、文件与摘要，区分可以继续、已经完成、明确失败和无法判断。原生候选/多文件路径的完整终态可以只读复用；OpenEvolve 的完成状态恢复则会重新本地准入和评分已有源码，但不重启外部 producer。发布中断可按日志补齐已经授权的登记；无法判断是否执行过的现场不会仅凭目录里出现文件就自动重跑。历史单文件流程的手动 attestation 是专门的异常恢复入口，不是正常多文件求解每一步都要求用户填写的手续。

普通任务另有自己的恢复语义：中断的 running task 会被标记为 uncertain，显式恢复可能再次调用 runtime。因此不能对所有普通工具副作用承诺“恰好执行一次”。`recover` 命令生成持久建议，`resume` 才执行恢复；两者职责不同。

公开 `status` 和底层 `run_status` 目前可能不同：父任务的合同接收已成功，演化子任务却可能失败。CLI 会结合 preparation、child 和 delivery 投影有效状态。Feature 142 将进一步修正新自动任务的父编排生命周期，使父任务保持运行直到最终交付，而非只靠显示层组合状态。

## 6. 预算与取消的当前边界

当前已经有多层预算：普通 Controller 活动执行时间、运行时单次超时、模型 profile 的调用限制、Agent 工具次数、每候选显式工具预算、preparation 单次请求与总时长，以及产物大小等限制。

普通 Controller 的活动预算从每次 `resume()` / `run_agent()` 开始计时，不是跨合同编译、用户等待和多次恢复累积的持久总时限。Feature 142 规划的也是一次活动执行预算；人工答复后的新执行沿用原策略，但已观察到总预算耗尽的终态不能靠 resume 补时。

普通 `run --detach` 和普通 `solve --detach` 已有本地后台进程与 PID/进程组登记；未完成的是自动多文件等路径的统一后台编排，并非整个系统完全不能后台运行。

不足之处是这些控制还没有由一个产品级总时限贯穿“合同 → 准备 → 全部候选 → 评分 → 父任务交付”。父 run 与 child 的取消、独立候选/评测进程组清理和后台 worker 生命周期也尚未全部统一。自动多文件入口当前明确拒绝 `--detach`。

Feature 139 的 50 分钟是这一次真实验收外层监控的预算，不意味着所有日常多文件任务已经具备统一的 50 分钟产品选项。Feature 142 目前只有 SDD：计划增加 `--solve-wall-timeout`，先贯通前台预算和父任务状态，再完成父子取消与进程清理，最后开放后台入口。

“隔离执行”目前主要是独立本地工作目录、受限环境、进程组、路径和文件规则；不能把它描述为已经部署了容器或完整操作系统沙箱。

## 7. OpenEvolve / Shinka 在哪里接入

融合思路是让外部框架提供候选，Lunar 继续负责任务合同、输入、实际执行、独立验收、状态和交付。共同边界是 producer result、seed manifest、身份和本地证据检查，不是把外部框架的运行状态当作 Lunar 成功。

| 路径 | 当前实现情况 | 尚缺部分 |
| --- | --- | --- |
| 原生 population | 可运行；多文件生成、执行、评分和父任务交付已通过原生离线完整流程 | 当前模型真实闭环验收及更广任务覆盖 |
| OpenEvolve | 有显式本地子进程策略与 handoff 接口，有离线协议验证 | 当前自动多文件 seed 接线、真实框架效果验收 |
| ShinkaEvolve | 有已完成结果的只读导出与通用 producer/seed 转换 | 直接启动调度、自动多文件接入、真实效果验收 |
| 远端 producer/material | 有协议、身份和已完成材料的接入边界 | 不能据此视为通用远端计算集群或多文件全链路已完成 |

当前多文件 pipeline 与 `seed_manifest` 同时使用会被明确拒绝，这也是外部多文件接入的实际代码缺口。当前支持范围内的独立源码约束是 `python_file_count`；它能核验源码文件数量，不能证明 helper 确实被调用、某个依赖确实使用或程序满足任意执行行为要求。超出支持范围的 source/execution 约束会提前拒绝。

## 8. 架构评估与下一步

当前最有价值的基础是：状态不依赖模型记忆，产物可定位，生成、执行和评分有独立记录，外部候选可以沿同一套核验流程接入。这些基础让失败诊断和后续接入新生成器有实际落点。

主要负担在编排层。`cli.py`、`controller.py`、`evolution.py` 已承担很多入口、兼容和状态转换职责；普通、单文件演化、多文件演化各自形成了生命周期分支。恢复与验证模块细分很多，但任务级的时间、取消与后台所有权还没有同步集中。

建议按以下顺序继续，不把大重构作为可用性的前置条件：

1. 完成本次真实多文件闭环验收，明确失败发生在哪一阶段或证实完整交付。
2. 按 Feature 142 建立共同的自动求解编排边界，统一活动执行时限、父子状态和停止传播；保持已有 profile 和执行身份不变。
3. 完成本地进程清理验收后开放后台运行，收敛前台、恢复和后台的重复逻辑。
4. 将 OpenEvolve/Shinka 的多文件候选接到现有流水线，逐个做有界真实验收。
5. 再扩展复杂输入、跨文件依赖、执行方式和通用仓库任务；用代表性任务验证能力，而不是把小型样例的成功外推成通用可靠性。

## 9. 阅读源码的入口

- [CLI](../src/famou/cli.py)：`_solve`、`_solve_evolution`、`_solve_payload`、`_status_projection`。
- [Controller](../src/famou/controller.py)：`resume_conversational`、`resume`、`_execute_task`、`run_agent`、`run_evolution`、`cancel`。
- [自动准备](../src/famou/automatic_solve_bundle.py)：`prepare_automatic_solve_bundle`。
- [评测器编译与审查](../src/famou/evaluator_bundle.py)：`compile_evaluator_bundle`、`_compile_audit_suite`、`load_evaluator_bundle`。
- [多文件候选生成](../src/famou/agent_bundle_generation.py)：`generate_bundle_candidate`、`parse_bundle_agent_draft`。
- [多文件执行与评测管线](../src/famou/bundle_evolution.py)：`MultiFileCandidatePipeline`。
- [演化引擎](../src/famou/evolution.py)：`CandidateArchive`、`PopulationStrategy`、`OpenEvolveStrategy`。
- [独立候选评分](../src/famou/candidate_evaluation.py)：`evaluate_candidate_execution`、`inspect_candidate_evaluation`。
- [父任务交付](../src/famou/bundle_parent_delivery.py)：`finish_bundle_parent_delivery`、`inspect_bundle_parent_delivery`。
- [Feature 142 规格](../specs/142-automatic-solve-lifecycle/spec.md)：下一阶段规格，尚未实现。

本文区分源码已实现、离线验收、真实运行和规划四种状态。当前真实运行结果由 Feature 139 的独立报告记录，架构存在一条执行路径并不自动意味着该路径对所有真实模型任务都已成功。
