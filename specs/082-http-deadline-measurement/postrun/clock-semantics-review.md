# 082 运行期限与 macOS 睡眠时钟说明

截至 2026-09-11 05:59 UTC 的只读核对，Lunar staged、AgentLoop、HTTP 父进程的期限，以及外层 `subprocess.wait(timeout=...)` 均以 Python `time.monotonic()` 计时。当前解释器将它实现为 macOS `mach_absolute_time()`，该时钟不累计系统睡眠时间。因此不能用“当前 UTC − 启动 UTC”直接判定这些期限已经耗尽。

**撤回此前按连续墙钟推算的本地 13:56 完成 ETA。** 现有证据没有给出精确累计睡眠时长，也没有启动时的逐进程时钟对照，无法据此换算一个新的可靠完成时刻。此说明不认定 081 deadline 缺陷，不证明某次网络异常由睡眠引起，也不改变任何当前运行条件或预算。

## 证据范围

- Lunar 固定源码提交：`e36b103fd6fc4a64304d16ae446e0383dab0a8a8`。下述仓库源码行号按该版本核对，082 的原文件保持冻结。
- 082 预注册 SHA256：`880761221b0ac2bb11acaffac2dbb8312171ae91adcc6da5ffd06763d2546bdb`。
- 已保存的[主机功耗与时钟投影](/Users/liminghan/Documents/lunar_agent/specs/082-http-deadline-measurement/postrun/observations/20260911T055914717921Z-host-power-time.json)，观察 UTC 为 `2026-09-11T05:59:14.717921+00:00`，SHA256 为 `1f8b8f6bfa23838d86c624997e6af0fc88413d3370b9d7a2dab94b2d449c43ea`。本说明复用 root 已采集的结果，没有重跑时钟或 runtime identity probe。
- 额外核验仅为源码、标准库、SDK 文件及解释器二进制的静态读取（`nm`/`otool`）；没有执行解释器探测、网络、测试、候选或模型请求，没有修改电源设置、进程状态或 campaign 输入。

## 各层实际期限

| 层 | 起点与时钟 | 行为及源码依据 |
| --- | --- | --- |
| staged 共享工作期限 | `run()` 设置 `time.monotonic()` 起点 | `max_wall_seconds − 已用 monotonic − reserve_seconds`。082 的 5400 秒减 120 秒预留，形成 5280 秒工作窗口；不是 `启动 UTC + 5280` 的绝对日历闹钟。`src/famou/staged_workflow.py:208–234`。 |
| Master / Build / AgentLoop | 每次 AgentLoop 调用记录 monotonic；其上限来自共享剩余预算 | Master 取 `min(1200, 共享剩余)`；Build 调用拿共享剩余。AgentLoop 每次计算 `timeout − (monotonic − started)`，并将剩余预算传给模型、将相同期限传给工具。`staged_workflow.py:232–235、280–296`；`agent_loop.py:204–231、300–313、577–583`。 |
| Build 协作边界 | Build 的 monotonic 起点；同时检查轮数 | 2400 秒或 32 轮是在安全边界检查的条件，不是独立的异步硬杀时刻；API 异常不能变成合法 checkpoint。`staged_workflow.py:280–308`；`agent_loop.py:210–222`。 |
| HTTP 父进程 | 请求开始时 `deadline = monotonic() + seconds` | 编码后、IPC 等待前后、解码后均检查；`communicate(timeout=remaining)` 限制等待，失败后回收子进程。`src/famou/http_transport.py:180–236`。 |
| HTTP worker | 接收同一个绝对 monotonic deadline | 打开响应前重算剩余时间，传给 `opener.open`。底层 socket/网络还可能提前报错；不能把一切 transport timeout 等同于父进程 deadline。`http_transport.py:329–361`。 |
| subject 外层 5430 秒 | native RegisteredExecutor 调用 `_default_executor`，后者 `Popen.wait(timeout=outer)` | Python 标准库以 monotonic 判断超时；不是 UTC 5430 秒的独立监督器。超时后才 killpg、wait 回收，再写终止事件。`specs/069-webagent-normal-workflow/measurement/worker.py:308–330`；`src/famou/effect_trial.py:633–659`。 |
| slot 外层 9300 秒 | `execute_slot` 的 `child.wait(timeout=9300)` | 同样走 Python monotonic；超时/异常后有 SIGTERM、最多 10 秒等待、必要时 SIGKILL 和回收。`specs/069-webagent-normal-workflow/measurement/campaign.py:23–63`。 |

082/078 wrapper 复用 074 的两槽入口，074 明确绑定上述 native worker/campaign 执行器：`specs/082-http-deadline-measurement/measurement/{campaign,worker}.py`；`specs/074-corrected-staged-measurement/measurement/worker.py:14–22` 和 `campaign.py:19–24`。本说明没有加载或执行这些 wrapper。

启动记录使用 `time.time()` 写 Unix 时间，而记录中的 `elapsed_seconds` 使用 monotonic 差值（native worker:311、317、330；native campaign:48、50、62）。campaign 总终止 UTC 则在所有 slot 返回后记录（074 campaign:146–150）。所以墙钟观察、subject 起点、staged 起点、进程回收和最终文件出现，本来就不是同一个事件。进程调度及回收还可带来额外间隔，不能把文件未出现当作恰好跨过某层期限的精确测量。

## Python 与 macOS 的具体时钟语义

仓库 `.venv/pyvenv.cfg` 记载 CPython `3.13.12`，`.venv/bin/python` 指向 `/Users/liminghan/miniforge3/bin/python3`。root 已保存的时钟观察是：

| Python API | 已观察到的实现 |
| --- | --- |
| `time.time()` | `clock_gettime(CLOCK_REALTIME)` |
| `time.monotonic()` | `mach_absolute_time()` |
| `time.perf_counter()` | `mach_absolute_time()` |

静态交叉核对当前 `/Users/liminghan/miniforge3/bin/python3.13`：`_time_monotonic` 在地址 `0x100336d78` 调用 `_py_get_monotonic_clock`；后者在 `0x10028e328` 调用 `_mach_absolute_time`，并包含实现名称字符串 `mach_absolute_time()`。这没有执行目标 Python，也不是对正在运行进程的 attach 或采样。

本机 SDK 的权威接口说明支持该语义：

- `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/mach/mach_time.h:58–62` 将 `mach_continuous_time` 描述为 “like mach_absolute_time, but advances during sleep”。
- `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/share/man/man3/clock_gettime.3:78–84` 明确 `CLOCK_UPTIME_RAW` 在系统睡眠期间不前进，且其值等同于经 timebase 换算的 `mach_absolute_time`。
- 同一 man page 的 67–69 行反而说明 macOS C API `CLOCK_MONOTONIC` 会在睡眠期间前进。**不能泛化为“macOS 所有 monotonic 时钟都不计睡眠”**；这里依赖的是已核验的 Python API 到 `mach_absolute_time` 的绑定。

本机 `/Users/liminghan/miniforge3/lib/python3.13/subprocess.py:54` 使用 `from time import monotonic as _time`。POSIX `_wait` 在 2053–2079 行以 `_time() + timeout` 建立终点，循环扣剩余时间；`communicate` 在 1217、1255–1268、2144–2155 行使用相同的终点与超时检查。因此 subject 和 slot 的外层 timeout 不会自动补上系统睡眠时长。

这里的“系统睡眠”不是 Python `time.sleep()`，也不是进程等待 I/O、未被调度或消耗很少 CPU。主机正常运行时，这些等待仍累计到该 monotonic 时钟。不能把它误称为 CPU 执行时间，也不能假定只要日志静默就不计时。

## 已有功耗投影能说明什么

已保存观察覆盖本地 `2026-09-11 12:28:28 +0800` 至 `13:59:14 +0800`；投影含 33 条 `Sleep`、35 条 `Wake`、32 条 `DarkWake` 时间戳与枚举。原始 `pmset` 日志、事件原因及完整字段没有保存，主机配置没有改变。

这证实本轮时间窗存在记录到的相关电源事件，足以否定“可以无条件假设全程连续清醒计时”。但该投影不是逐进程时钟轨迹，不能简单把相邻 Sleep/Wake 或 DarkWake 两两相减、相加就得出准确暂停时长；也不能据事件条数补算某个请求实际少计了多少秒。两三分钟进度间隙本身更不能替代系统睡眠证据。

因此，在 05:57:20 UTC 观察到墙钟从启动约过了 5325 秒，却尚未出现 slot 1 终止文件，只能说明尚无该终止证据；它不足以证明 staged 的 5280 monotonic 秒已用完。即使后来 UTC 差值超过 5430 秒，单凭这个差值也不能断言外层 `wait` 失效。当前结果仍须由原生终止记录、回执和既定审计判定。

邮政终止请求的 `14901 ms` 与 `3970214 ms` 是另一个已接受的请求观察。功耗事件与上述时钟语义不能定位其 DNS、TLS、代理或 provider 原因，不能证明该异常由休眠引发，也不授予重试或重放权限。

## 当前处理边界

继续以已冻结运行、原生终止和已有审计为准；不修改 timeout，不启动新的保活或防睡眠设置，不重启、不重试候选，不在活跃评测中替换时钟。暂不发布新的固定 UTC 完成承诺。

`max_wall_seconds` 在当前实现中是上述 monotonic elapsed 语义，而不是无条件累计系统睡眠的日历秒。这是应在最终测量限制中披露的事实。是否在后续版本明确区分“含系统睡眠的真实经过时间”与“主机运行期间的经过时间”，需要另行定义和验证；本次观察不直接推出代码修改或 081 修复结论。
