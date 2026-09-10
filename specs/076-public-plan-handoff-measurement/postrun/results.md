# 公共计划交接真实评测结果

两个预注册尝试均已结束，有效解为0/2。邮政首次通过修复后的Master计划验收并进入
Build，随后模型调用失败；钣金在Master模型阶段超时。两槽均无完成回执或exact harness
评分，validity/overall/quality、完整失败用量和费用均为null，不能解释为零分。

| Slot / Case | Subject耗时 | 原生诊断 | 已核对的阶段证据 |
| --- | ---: | --- | --- |
| 1 钣金套料 | 1200.259秒 | model / timeout | 6次模型响应、12次工具结果；无最终计划、Build或候选输出 |
| 2 邮政揽收优化 | 2190.554秒 | model / model_failed | Master计划已验收；Build有19次模型响应、24次工具结果，已写求解产物但无完成回执 |

邮政的8项计划包含公开目标词汇combined_score、score与evaluator，075后的现有校验器
接受了这份真实计划。Build目录保留solve.py、output/solution.json和output/assignments.csv，
缺少_agent_summary.md，未发生checkpoint或续跑。只检查候选文件元数据，没有执行候选
或补跑评分。原生诊断的http_status为null；不能从model_failed进一步断言provider宕机、
限流或具体传输故障，也不能将这次失败记成总预算超时。

钣金轨迹是公开订单/库存统计、尺寸与分组检查。前三次run_command使用字符串化JSON
argv而被拒绝，下一轮相同三条命令改为普通命令字符串后成功。没有证据表明它已进行优化求解，
也没有逐调用耗时证明参数错误或规划职责导致1200秒超时。

邮政Master有5次已完成模型响应和7次工具结果，加上Build共24/31；state保存的41291
tokens仅覆盖已记录的Master账本，不能充当整轮用量。钣金usage unavailable中的初始化
0也不表示实际零消耗。精确独立Master耗时仍为null；表中的耗时来自subject进程标记。

本轮产品固定96d5a600f03e5401753efc6f579d2ff14fe839be，登记提交
2916041947c49800b3dda0f5c463014292291aae已在唯一启动前推送。两例各一个新S尝试，
GLM-5.2，一波并发2；Master1200/build2400/reserve120秒，共享5400秒/200工具/800万
累计tokens及至多一次合作式续跑。失败不补位，未执行WebAgent、查询公司平台、探测
模型或回填历史结果。历史069普通流程2/2只作背景，不进入分母；不同案例不合并质量
均值，单次交接不能证明修复的因果效果或稳定成功率。

独立最终审计及root逐项复验通过225项证据SHA；37源码、111冻结文件、24历史锚点均
保持不变。watcher98576退出0。终局检查汇总80份启动/进度身份证据，已知9个PID、
5个PGID与可见argv/cwd关联进程均无残留。原生subject marker的child IDs仍为null，
实际身份来自独立快照；这是时点可见性检查，不能排除已脱离关联、改变cwd和argv的后代。

Manifest SHA256：6690a02223aa3ea34bd5f88d9482d75d4a087857d69edd4245ac04479a321b76。
Final audit SHA256：95d54b9d3c349fd3f83bb0cb1c052694cb3e21247b6c8a21477017e31848b62e。
Final report SHA256：88ab75a77ec0eede74dd0d1cb1c9a4513e9e2a3de8f58de5ced3f0afb7830f96。
Process check SHA256：1349dd5d00190408938bf61f8b1318f3fe36880778f5687dfd9ffbdc115aaf57。
Native summary SHA256：7f58f6ce655023ae4690ea2daf19ae0025d5d9e7de3310315f1a807e37bcb3b8。

Feature077在隔离worktree明确Master的当前规划职责：先交最小Build计划，原始任务完整
保留，未知细节留给Build。它不改变工具、预算、评分权威或重试策略，尚未参与真实测量；
先封存本批，再合入独立审查通过的实现。后续仍须新预注册验证完整交付，不能把本批
候选文件或离线测试当作有效解，也不能重开这两个失败槽。
