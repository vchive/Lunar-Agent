# 074 钣金槽终止诊断

钣金槽在 Master 阶段超时，尚无最终计划响应。原生失败诊断明确记录 `code=timeout`、`stage=model`；subject 用时 1200.203 秒、返回码 2，与登记的 Master 上限 1200 秒一致。
外层用时 1200.376 秒、worker/outer 返回码 0 表示失败记录正常封存，不代表产生有效解；登记 subject 外层上限为 5430 秒，本次没有触发该外层超时。

- Master transcript 共 16 条消息：system 1、user 1、assistant 6、tool 8。6 条 assistant 均包含工具调用，末条是工具结果，没有最终计划响应。
- 8 次工具调用为 read_file 3、list_dir 2、run_command 3；本诊断只读历史调用元数据，未执行任何命令或候选。
- 工作流为 `master_running`，无 `master.json`、Build transcript、subject receipt、harness 启动或 `_agent_summary.md`。
- 只检查目录与文件元数据：workspace 仅有 request、failure receipt、3 个 workflow 文件和 3 个公开 case 文件，没有候选输出；没有打开候选文件。
- 原生 record 为 `failed`，usage、cost、extraction、Validity、Overall、Quality 均为 `null`。

workflow state 的 `usage.available=false`，其中 rounds、tool_steps、elapsed_ms 的初始化 0 不能当作真实零用量。可确认完成了 6 条模型响应和 8 条工具结果，但不能据此补全超时请求的 tokens 或费用。Master 独立精确耗时仍为 `null`。
本槽没有最终 Master 响应，因此不能归因于 JSON 包络或计划语义校验失败。

核对了 manifest 镜像、终止绑定、worker→outcome→record/report、request→failure、config 和相关冻结源码；诊断前后所读 19 个证据文件与 workspace 元数据均未变。
未调用模型、harness、WorkflowController 或恢复，未读取或执行候选，未改动 campaign/冻结文件。

预注册 SHA256：`b154975d9557b9697fcdc7915de3ab7bb225165c6aaa1c6c0ab3f432a2123229`。

结构化诊断：[slot-001-diagnostic.json](slot-001-diagnostic.json)，SHA256：`f13a67e9999b6ec48f2c63e0f4494c6ab893c86def58fa591348dd1f1769a5d6`。
