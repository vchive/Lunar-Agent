# Feature 085: Population-First Evolution

**Feature Branch**: `085-population-first-evolution`

**Created**: 2026-09-11

**Status**: Draft

## Problem

Lunar 当前把演化策略分成 `loop`、`population` 和 `openevolve`。其中 `loop` 是单链式
“基于当前最好候选继续生成”的历史策略，不具备完整的 population 选择、多样性维护和
种子 admission 语义。继续把它作为默认策略会让普通演化和深度演化存在两套不一致的状态
模型，也容易把无效候选或失败轮次误认为正式演化进度。

## Goal

将 Lunar 的生产演化路线收敛到 **population-first**：所有新的本地深度演化默认使用
`PopulationStrategy`；OpenEvolve 作为显式外部后端；`LoopStrategy` 不再作为新任务的
可选策略。普通 Master→Build 仍独立完成，演化仍是显式 opt-in 阶段。

## Scope boundary

- `AgentLoopRuntime` 和 `--agent-loop` 是模型/工具交互运行时，**不删除**。
- `effect-deep-trial` 的 `strategy=loop` 是 Feature 051 的历史测量协议标识，**不改写**
  已封存报告、manifest 或 receipt。
- 旧 loop archive 可以只读读取和生成诊断；不允许从旧 loop 状态继续创建新的 loop 迭代。
- 本 Feature 不实现远端 famou-v2 调用；verified seed admission 由 Feature 084 提供。

## Requirements

### FR-001 新任务默认 population

未显式指定策略时，contract compiler、`solve --evolve`、`evolve` 和 benchmark 均使用
`population`，且默认配置、fingerprint、帮助文本和 JSON 输出保持一致。

### FR-002 禁止新 loop 任务

新建 contract 或启动新的 evolution run 时，`loop` 必须被拒绝并返回固定错误码；错误
信息应指向 `population` 或显式的 `openevolve`。不得把新 loop 请求静默转换为 population，
避免调用方误以为仍在运行旧策略。

### FR-003 旧状态只读兼容

读取历史 loop contract、archive 或 result 时，系统可以展示其状态和结果，但不得执行
`LoopStrategy`、推进 iteration、写入新的 loop candidate，或将其结果伪装成 population。

### FR-004 population admission

Population run 在 generator 前必须通过 Feature 084 的 verified seed admission。没有带有
本地 evaluator receipt 且 `validity == 1` 的 seed 时，运行 fail closed，不推进 iteration，
不修改 active population。

### FR-005 正式轮次与失败语义

只有通过 admission 且完成一次候选生成/评估的 population iteration 才计入正式轮次；
candidate failure、evaluator timeout、worker unknown 和 run failure 必须分别持久化。

### FR-006 保持 lineage 和恢复

每个候选必须保存 candidate ID、parent ID、generation、iteration、evaluator receipt 和
source/dependency/contract/environment fingerprint。resume 必须校验 fingerprint；不匹配
时 fail closed。

### FR-007 OpenEvolve 边界

`openevolve` 只能作为显式候选生成/搜索后端；其输出必须经过 Lunar 本地 exact harness
和 evaluator receipt 后才能进入 population 或最终交付。外部得分不能直接成为 Lunar 分数。

### FR-008 历史协议不变

本 Feature 不修改 Feature 051/074/076/078/082 的封存字节、协议身份或历史统计。

## Acceptance scenarios

1. 不指定策略的新的 `solve --evolve` 运行，其配置和结果声明 `population`。
2. 指定 `--strategy loop` 创建新 run 时，在任何 generator、worker 或 population mutation
   之前失败，并返回迁移提示。
3. 读取旧 loop archive 可以得到历史状态，但 resume 被拒绝且不会新增候选。
4. 无有效 verified seed 的 population run 在第 0 轮失败，archive 中没有 active candidate。
5. 一个有效 seed 能启动 population，恢复时 source 或 evaluator fingerprint 改变会被拒绝。
6. `--agent-loop` 的普通模型工具交互测试保持通过。
7. `effect-deep-trial` 历史 fixture 的 protocol、strategy metadata 和报告 SHA 保持不变。

## Migration order

1. 先将新默认值和 CLI/contract 选择切换到 `population`，加入旧 loop 只读检测。
2. 接入 Feature 084 的 seed admission、receipt 和 fingerprint 校验。
3. 将 active tests、README 和新 benchmark 改为 population-first。
4. 在历史读取兼容稳定后，删除 `LoopStrategy` 执行实现及新建入口；保留必要的历史解析器。

## Non-goals

- 不保证 population 一定提高有效解率；需要新的固定真实测量才能判断。
- 不把 WebAgent 的远端 evolve 控制面引入默认本地路径。
- 不删除所有名为 loop 的代码或历史文档。
