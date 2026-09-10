# Feature 078：Master 规划职责真实测量终局

两个新 S 槽均已结束：Master 计划验收 **2/2**、进入 Build **2/2**，最终有效解 **0/2**。
两槽均在模型调用阶段超时，未生成 subject 完成回执、未运行 exact harness，分数保持
`null`。本轮说明该配置下两个 case 完成了阶段交接，但没有完成有效解交付。

| 观测 | 钣金套料（slot 1） | 邮政揽收（slot 2） |
| --- | ---: | ---: |
| Master 计划验收 / 进入 Build | 是 / 是 | 是 / 是 |
| Subject 原生耗时（秒） | 5280.390 | 5280.378 |
| Subject 退出码 | 2 | 2 |
| 安全诊断 stage / code | model / timeout | model / timeout |
| HTTP 状态 | null | null |
| 已观测模型响应 / 工具结果事件 | 16 / 21 | 14 / 21 |
| 合作式检查点 / 续跑 | 无 / 否 | 无 / 否 |
| Subject 回执 / harness | 无 / 未启动 | 无 / 未启动 |
| validity / overall / quality | null / null / null | null / null / null |
| 完整失败 usage / cost | null / null | null / null |

固定分母为两个登记槽，各启动一次；历史尝试不进入分母，失败未补位。
`valid_solution_rate=0/2` 是完成率，不能改写成质量分 0。没有跨 case 质量均分。
逐槽元数据检查：钣金仅保留 1403 字节的 `analyze.py`，邮政未发现候选文件；两槽均缺少
计划声明的全部交付路径。详见[钣金诊断](slot-001-diagnostic.md)和[邮政诊断](slot-002-diagnostic.md)。

## 解释边界

本轮保持 GLM-5.2、已有 CC Switch 配置和 exact harness；只测量 077 的 Master user
prompt。源码固定 `fba6ab8cf5b27d3bd1b42f353907a6ae21c25ef9`，未包含隔离开发的 079。
Master 1200 / Build 2400 / reserve 120 秒、共享 5400 秒 / 200 工具 / 800 万累计 tokens，
一波并发 2、至多一次同进程合作式续跑的登记条件保持不变。

Build 2400 秒是完整工具轮次之后的合作式边界；它不会打断正在等待的模型调用。
运行代码从共享期限中预留 120 秒，因此约 5280 秒的 subject 终止与该配置一致。
本轮未产生可续跑检查点，不能据此评价续跑收益；也不能由这两个样本认定提示修改有
因果效果、流程已经稳定，或更长预算必定有效。

两槽的持久化 workflow state 最后仍为 `build_running`，但原生 subject、worker 和
campaign 均已终止；这个阶段字段不代表进程仍在运行。state 的 usage 仅为 Master
结束时保存的快照，不是完整失败用量。精确、独立的 Master 耗时仍未知。
诊断的 `mode=normal` 是既有 subject schema 字段，本轮实验臂仍为 S。
`model/timeout` 及空 HTTP 状态不能进一步确定服务端原因或最后请求的精确等待时长。

## 核验与封存

登记 `e76a3a341a90703f4ba91a9e14e33ca81a76c488` 已在唯一启动前推送；启动时间为
2026-09-10 22:17:13 +0800。只读 watcher 7684 于两槽终止后退出 0，保留 174 份进度
快照及 root 实际观察到的退出记录。没有额外模型探测、重试、候选执行或补跑评分。

独立完整审计及 root 再验通过 **236 项证据 SHA**，37 源码 / 114 冻结文件 / 30 历史
锚点均一致。原生汇总已嵌入独立审计；最终进程核查联合启动标记、初始快照和所有进度
身份，未发现已知 5 个 PID / 5 个 PGID 或可见 argv/cwd 关联进程残留。
这仍是时点可见性检查，不能排除未曾捕获且脱离身份、改变 cwd/argv 的后代。

- Manifest SHA：`605cfd030b3b65e9bc1995157f44acdbbbbe7e55837b6f4a27b7042afb996804`
- [独立最终审计](final-audit.json)：`a6cea5e657ef38fe7bd23bdce86b8361adef038313d9b691ec892833217de5a4`
- [原生投影报告](final-report.md)：`eac8ba34a37594fbe87bcebc12224866bf13ebf4c6e0658efdf53b3c56f3a6c9`
- [最终进程核查](final-process-check.json)：`8e764805b77f13cb047ba35d33e03e2281d25629495ffc2064391fa905f61a09`
- 原生 summary SHA：`33314aad581d81aa46114a20986d464d1a386e39054aa12da31c3eb566e7124d`

下一步在本批封存推送后合入已独立审查的 079 安全模型失败诊断；它不能追补本批缺失
证据或改善已封存结果。本轮不自动登记新 campaign。普通流程的历史 2/2 有效保留为
已有交付证据，分阶段流程的后续目标仍是完成 Build → 原生回执 → 独立有效解。
