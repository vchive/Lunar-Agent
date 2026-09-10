# 076 邮政槽终止诊断

邮政槽通过 Master 计划验收并进入 Build，但在完成 subject 交付前发生模型阶段失败。原生诊断为 `stage=model`、`code=model_failed`，HTTP 状态为 `null`；它没有记录为 timeout，也未保存足以细分网络、响应解析、空响应等问题的原始异常。

- Subject 用时 2190.554 秒、返回码 2；外层用时 2190.746 秒、返回码 0 表示失败记录正常保存。
- Master 有 5 条模型响应、7 条工具结果；Build 有 19 条模型响应、24 条工具结果，合计与失败诊断的 24/31 一致。
- Build transcript 末条是 `exit_code=0` 的工具结果，此后没有最终 Build 响应。该工具结果及本地指标不能代替 exact-harness 分数。
- 最终审计确认有效 Master record、进入 Build 和 Build transcript；状态停在 `build_running`，无 checkpoint、未续跑。
- 仅按目录元数据确认 `solve.py`、`output/solution.json`、`output/assignments.csv` 及若干分析脚本存在；缺少 `_agent_summary.md` 和 subject receipt。未读取候选内容、未计算候选文件哈希、未执行或评价候选。
- 未启动 harness，原生 record 为 `failed`；extraction、Validity、Overall、Quality、完整 usage 和费用均为 `null`。

workflow state 中 41291 tokens、5 rounds、7 tools 只是已保存的 Master 快照，不包含完整 Build 及失败请求，不能作为整轮用量。Master 独立精确耗时仍为 `null`。

075 后本次观察到计划交接成功；单次尝试不能证明修复的因果效果或稳定成功率。候选存在也不能抵消缺失的原生 receipt，不能事后绕过门禁评分或补位。

所读 24 个证据文件的登记与原生链均核对一致，诊断前后字节及 workspace 元数据未变。未调用模型、harness、Controller 或恢复，未读取或执行候选，未修改 campaign/冻结文件。

预注册 SHA256：`6690a02223aa3ea34bd5f88d9482d75d4a087857d69edd4245ac04479a321b76`。

结构化诊断：[slot-002-diagnostic.json](slot-002-diagnostic.json)，SHA256：`4e6762be7b5149c11798622d9ae497bf480ca57072a0659a14a20057714a64c0`。
