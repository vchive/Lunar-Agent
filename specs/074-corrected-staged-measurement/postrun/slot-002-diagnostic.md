# 074 邮政槽终止诊断

邮政槽未进入 Build 的首个可确定复现阻断，是 Master 计划语义门禁误判公开目标词汇。
073 修复后的 JSON 包络解析已经通过：最终响应 1944 字节，唯一 `json` 围栏内是 8 项计划和 4 个安全输出路径。

`workflow_checkpoint.py` 的 `_FORBIDDEN` 用不区分大小写的子串正则匹配 `score`。
计划第 3 项“Implement the objective scorer matching problem.json”首先触发；第 7 项 `combined_score`、第 8 项 `objective/score`也触发。
公开 `case/data/problem.json` 第 9 行有 `score_direction`，第 12 行声明目标公式，第 19 行有 `combined_score`。
Master 的 5 次工具调用全是对公开 case 路径的目录列举或读取。

- Subject 在 167.136 秒后以返回码 2 结束；外层 worker 正常保存失败记录，因此外层退出码 0 不代表解成功。
- 工作流停留在 `master_running`；无 `master.json`、Build transcript、已接受 subject receipt 或 harness 启动。
- 原生记录是 `failed`；extraction、Validity、Overall、Quality 全为 `null`。
- 观察到的 usage ledger 为 4 轮、5 次工具、24748 tokens；Master 精确耗时仍为 `null`。

失败 receipt 只保存 `runtime_failed`，没有原始异常栈。本诊断使用冻结代码的纯解析与校验函数，确定性复现上述首个阻断；没有把推断写成已记录的异常。
登记 manifest、终止标记、worker→outcome→record/report、request→failure、workflow config 与相关冻结源码的字节关系均核对一致；诊断期间所读证据未变。
未执行候选、模型、harness、WorkflowController 或恢复；未改动 campaign 或冻结文件，未产生新评分或补位尝试。

预注册 SHA256：`b154975d9557b9697fcdc7915de3ab7bb225165c6aaa1c6c0ab3f432a2123229`。

结构化诊断：[slot-002-diagnostic.json](slot-002-diagnostic.json)，SHA256：`bfeead9a311265ef92bf2c0204d3100fabd4c136e3ebbc47bc410a21bf23de61`。
