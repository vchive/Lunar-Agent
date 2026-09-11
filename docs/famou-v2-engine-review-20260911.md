# famou-v2 product/dev 引擎审查（固定提交 2026-09-11）

本文只审查 Git blob `99ea1a3da9d310c723180717efd83d67335e0336`（`product/dev`）中的 engine/evolver/strategy router、生成—选择—评估—种群数据链、初始化、预算与持久化；未 checkout、未执行模型/候选/服务，也未读取凭据。其他分支只做关键差异：`master`=`b7df91ac8c8200be0ba22ee6fa807ad9b14aecb7`、`product/online`=`9c690b269969e8e6eb2814e3ca62e1872dc62a42`、名为 v2.5=`c5d31cac091534a0daa1ad4839753440ca0cb3e6`。在 `master` 到 `product/dev` 的三文件 diff 中，实际新增集中在 `evolver.py`（257 行）：初始化依赖失败/无可用 seed 校验、初始化失败信号、恢复计数对齐；没有证据表明只是把五轮固定重跑改名。

## 数据链与失败语义

`Evolver.run`（`famou/controller/evolver.py:895-1021`）先让 strategy 在 iteration 0 生成 enrichment rollout，再启动 backend；新实验执行依赖解析、初始 seed enrichment、保存 seed、初始化结果校验和 feasibility gate，随后才进入 streaming evolution。`_run_evolution_with_backend`（:1022-1245）使用 `_IslandTracker` 分发 `(island, iteration, attempt)`，完成一个成功 rollout 才消耗正式 iteration；失败 rollout 放入 retry queue，重试同一 formal iteration；fatal rollout 终止。成功结果才调用 `_update_experiment`，记录 archive、island population、history、state updates、结果文件和 iteration（:2149-2276）。因此 retry 不是额外的“第五轮”；它不推进 iteration，但会重新执行该轮 pipeline。

engine 的 pipeline 是 Select → Generate → Evaluate → Judge，并递归注入 LLM/env/embedding。`RolloutEngine._execute_pipeline`（`famou/controller/engine.py:429-676`）按模块顺序执行，任一模块失败即使 rollout 整体失败并停止后续模块；`ModuleValidationError` 与 `FatalRolloutError` 的重试分类见 :254-337，fatal/生成校验失败和普通失败的最终状态在 :623-641。重试调用同一 module/context/result，不等于重建完整 rollout；因此外部接入必须明确副作用和幂等性。

策略 route 的默认方向映射（`famou/controller/strategy_router.py:36-47`）是 machine_learning→`example_strategy`、combinatorial_optimization→`adaptive_cluster`、math→`standard`、other→`example_strategy`。显式合法方向优先，其次持久化 decision，再 LLM 分类，失败 fallback 为 `other`（:363-514）。该 router 选择的是策略构造，不是独立 evaluator 或外部 solver 的可信度证明。

一条具体主链 `strategies/adaptive_cluster.py:52-63` 组装 `ClusterAdaptiveSelect`、`MutationGenerate`、`EvaluateModule`、`LLMJudge` 和 `ClusterPopulation`。Select 从 cluster 中作探索/利用父代和 inspirations（`modules/select/cluster_adaptive.py:59-201`）；Generate 产出 child；EvaluateModule 要求 evaluator 返回 `combined_score`、`validity`，并在执行失败时设置 validity/score 为 0（`modules/evaluate/base.py:103-255`）；成功 rollout 才进入 `ClusterPopulation.update_population`，按 feature vector 在线聚类、周期性离线重聚类并按岛容量丢弃低分项（`modules/population/cluster.py:21-134,395-425`）。这是一条有状态 population 链，不是仅对同一 prompt 做五次请求。

## 初始可行解和 verified seed handoff

product/dev 的初始输入是 `initial_programs`，而不是 Evolver 自动凭空生成；构造器要求新实验只能给 `initial_programs`，恢复实验只能给 `experiment`（`evolver.py:244-360`）。初始 program 先做依赖解析并可能安装缺失包（:472-531），再用与 rollout 相同的 enrichment modules 并行处理（:705-890）。失败被区分为 `no_score` 和 `invalid`；所有 seed 不可用时 `_validate_initialization_outcome` 直接失败（:612-675），开启 `feasibility_check` 时还要求至少一个 `validity == 1.0`（:533-610）。因此已有候选可以作为 verified seed，但必须携带可执行 code、依赖/环境提示、evaluator 产生的 `combined_score`/`validity`/error normalization，并通过该门槛；仅复制一个外部 score 或把候选塞入 archive 不能绕过权威 evaluator。

最小代码切入点应是一个本地、显式的 seed adapter（不接公司服务）：将公开契约的候选清单转换为 `Program`，保留 source/lineage/identity 元数据；在创建 Evolver 前将它们作为 `initial_programs` 传入；继续复用现有 `_enrich_initial_programs`、`_validate_initialization_outcome`、`_validate_initial_program_feasibility` 和 `PopulationModule`。若 seed 已有可信评估结果，也只能作为缓存/比较信息，是否可入 population 仍由本地 evaluator 重验。该切入点比先引入外部 solver/backend 更小，因为后者还需解决 worker/env、共享 state、retry 幂等和 exact evaluator 收据桥接。

## 预算和持久化边界

配置层明确有 LLM 单请求 `max_tokens`、`timeout`、transport `max_retries`（`config/settings.py:26-50`），环境执行 timeout（:137-150），experiment `max_iterations`/`checkpoint_interval`/feasibility（:480-545），岛 population capacity（:374-437）。engine 的 tenacity retry 是模块/rollout 层；evolver 的 attempt retry 是 formal iteration 层；代码中没有看到统一的跨模块 token/cost/wall-clock ledger。并行 backend 的 `wait_first_completed(timeout=300)` 只是等待轮询超时，超时后继续等待（`evolver.py:769-781`），不是全局 300 秒硬截止。

每个成功 rollout 会保存 program、result、history、strategy state；按 checkpoint interval 和 finally 保存 experiment + strategy checkpoint（`evolver.py:1170-1223,2425-2462`）。失败 rollout保存 result/日志但不入 population、history或 iteration；重启恢复从 `current_iteration + 1` 开始。对于 verified seed handoff，必须把 seed provenance、evaluator receipt/hash、依赖解析结果和 identity 写入持久化 artifact，否则恢复后无法区分“已验证候选”和普通初始代码。

## 与 Lunar 三路径的映射

Lunar staged Master→Build 使用共享 `UsageLedger`、工具步数 offset、transcript/checkpoint 完整性和 profile/identity/receipt；famou-v2 Evolver 没有等价的跨模块全局 ledger，`max_retries` 和 evaluator timeout 是局部限制。因此不能把 `CommandAgentAdapter` 或普通 backend 直接替换 staged Build。Lunar real effect-deep-trial 是固定 outer rounds，每轮 subject receipt 通过后才 exact harness 评分并形成 bounded feedback；famou-v2 retry/iteration 语义不同，且其 EvaluateModule 结果不是 Lunar exact harness receipt。Lunar 通用 solve/evolve 的 PopulationStrategy 可对应 famou 的 selection/population 思路，但仍需 evaluator、候选身份和持久化收据桥接。

## 对 SDD 的最小优先级判断

相对先做“单请求预算”优化，verified seed handoff 更高优先级：它直接解决当前无有效解时的冷启动和初始可行性问题，并能复用现有 population/strategy 数据链；单请求预算只会降低一次调用成本，不能证明候选可执行或让空 population 产生有效解。第一步应设计本地 seed adapter + evaluator receipt/provenance 契约；第二步才在该契约之上做跨轮预算/ledger。外部 famou-v2 solver/backend 作为后续实验选项，不能被描述为当前 Lunar S 测量已经接入。
