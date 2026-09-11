# Lunar Agent HTTP deadline评测（Feature 082）

状态：进行中，结果仍未决。

GLM-5.2，Master上限1200秒，共享总预算5400秒 / 200工具 / 800万累计tokens。

| Case | 状态 | 计划验收 | 进入Build | 续跑 | Validity | Overall | Quality |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| 钣金套料 | 运行中／未决 | 未观察到 | 未观察到 | 否 | null | null | null |
| 邮政揽收优化 | 运行中／未决 | 是 | 是 | 否 | null | null | null |

固定分母2；已终止0；已观察有效解0。
null是未知或未评分，不能当作零分；计划/Build/checkpoint不等于有效解。
Master精确耗时未记录，保持null；失败完整用量和费用未知时同样保持null。
每个case只有一次新尝试，历史样本不进分母，不跨case合并质量均值，也不声称修复因果效果。
本报告不检查操作系统进程存活，最终封存另有进程核对。
预注册SHA256：`880761221b0ac2bb11acaffac2dbb8312171ae91adcc6da5ffd06763d2546bdb`。
运行中或未启动槽仍未决，上述计数不是最终失败率。

## 终止请求诊断（仅辅助观察）

诊断不授予 subject receipt、harness 或分数权限；缺失或无效诊断保持未知。
请求耗时仅描述最终失败请求，不是 Master 精确时长，也不恢复失败请求的完整用量或费用。
本轮测量集成的079/080/081，不能单独归因 HTTP deadline，也不能倒推078失败原因。

| Slot | 诊断状态 | stage/code | HTTP | typed reason/status | phase | elapsed ms | timeout ms |
|---:|---|---|---|---|---|---:|---:|
| 1 | unavailable | null | null | null | null | null | null |
| 2 | unavailable | null | null | null | null | null | null |
