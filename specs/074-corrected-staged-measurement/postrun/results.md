# 修复格式解析后的分阶段真实评测

两个预注册尝试均已终止，有效解计数为0/2。两槽都未通过最终Master计划验收，未进入
Build、续跑或exact harness，validity/overall/quality与完整失败用量、费用均保持null。
这次已定位两个不同原因，不能统一归因于预算或模型能力。

| Slot / Case | Subject耗时 | 原生诊断 | 已核对的阶段证据 |
| --- | ---: | --- | --- |
| 1 钣金套料 | 1200.203秒 | model / timeout | 6次模型响应均带工具调用，8次工具结果，无最终计划文本或候选输出 |
| 2 邮政揽收优化 | 167.136秒 | runtime / runtime_failed | 唯一JSON围栏解析成功，公开目标词汇触发控制器的score子串黑名单 |

钣金耗尽Master上限，没有最终文本响应。仅由此不能证明更长窗口必定有效。邮政返回的
1944字节响应经073解析器成功得到8项计划和4个安全输出路径；首个可确定复现阻断是
计划第3项objective scorer命中score，其他项combined_score和objective/score同样命中。
公开problem.json本就包含score_direction、combined_score及目标公式，Master的5次工具
调用都是公开case目录的列举与读取。本例说明格式修复已通过，但计划内容的关键词规则
继续误拒绝正常任务描述。失败回执只有runtime_failed，没有原始异常栈；这里陈述的是
冻结校验逻辑对已保存响应的确定性首阻断复现，不伪称捕获了原始异常。

邮政状态保存了4轮/5工具/24748tokens的已观察账本；它不是完整失败用量或账单。钣金
state中的usage unavailable与初始化0也不能当成实际零消耗。精确Master独立耗时按登记
保持null，表中的时间来自subject进程标记。worker返回0只说明失败记录正常保存。

本轮产品固定c28e498，使用GLM-5.2，钣金、邮政各一个新S尝试，一波并发2。Master1200/
build2400/reserve120秒，5400秒/200工具/800万累计tokens及一次合作式续跑的共享边界
保持不变。没有补位、模型探测、WebAgent执行、公司平台查询、历史候选执行或分数回填。
历史069普通流程2/2、072结果仅作背景，不进入此次分母。这是一个配置的一次/案例观察，
不跨案例合并质量均值，也不能声称格式修复的因果效应或稳定成功率。

正式最终审计和root再次逐项复核通过205项证据SHA，含37源码、99冻结文件和18历史
锚点。注册27f7124b28ef9a7318c5f574a9ac97b16a718b9c已在启动前提交推送。最终已知
dispatcher/worker/subject PID与PGID、可见argv/cwd关联进程均未发现存活；原始subject
标记的child IDs仍为null，独立进程快照记录了实际PID/PPID/PGID。该检查是有明确可见性
限制的时点核对，不声称持续追踪了所有可能脱离关联的后代。

Manifest SHA256：b154975d9557b9697fcdc7915de3ab7bb225165c6aaa1c6c0ab3f432a2123229。
Final audit SHA256：c0f38b2df844152a6a8bca13036a15a031fb0df3c9f5dc560818f4c5f0f1447a。
Final report SHA256：a1c64aa7d248873c2d5636da3fdb98edcacd78a0943ce12d063abe6499f68503。
Process check SHA256：b28e746f1b81b834b47c0526b81c40fdfb4fae863deb0db88755082169e15e70。
Native summary SHA256：7139d20b10ce3fcb9d61242b47880836722ef72be9aecfc0965e9b9bc8eabe52。

Feature075已在隔离分支去除计划文字/普通产物名的语义黑名单，保持结构、路径与评分
权威边界并补充凭据路径拒绝。260项定向和1316项全仓测试、独立审查已通过。它没有
参与本轮测量；须先封存本批后合入。修复后的真实有效性仍需要新的预注册测量，不能
重开本次失败槽、回填计划验收或评分。
