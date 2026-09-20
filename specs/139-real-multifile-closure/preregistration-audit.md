# Feature 139 预登记独立审计

**日期**：原始审查 2026-09-19；离线集成独立复核 2026-09-20
**结论**：B001–B011 及请求/阶段时间关联的实现缺口已修复并完成离线复核；本轮审查未发现
剩余实现阻断。T007 完整双阶段验证已通过；本次离线实现检查点的具体 manifest/已推送登记
和真实唯一槽验收尚未完成，
不能将本结论当作正式登记、启动许可或真实成功结果。
**原始检查基线**：`HEAD=741900a1c8068d31094c25d27b1e4c7397b1dbb0` 加本轮未提交的
Feature 139 campaign/ledger 加固。下列行号对应此次审查快照，后续以函数名和阻断编号定位。

本审查只读取实现、执行合成复现和离线聚焦测试；临时原生 Store/workspace 使用仓库拥有的
合成候选/evaluator 和替代 provider 响应。未登记或启动真实 campaign、调用 provider，也未
执行历史生成源码。Feature 141 的既有产品验证不属于本轮实现的完成证明。
本文是整改依据，不是 registration、launch approval 或真实端到端成功报告。

## 当前整改状态（2026-09-20，离线实现复核完成）

工作树已包含并离线复验 B001–B006 的 campaign/ledger 修复及 registration/trust-root/inventory、
worker、observer、runner 和 supervision。实际 worker、retained summary 和原生 Store 回执也已
经过离线集成验证；下文 B001–B006 的复现描述保留原始审查快照，不代表当前修复仍能复现。

| 原始编号 | 当前实现与复验结论 |
| --- | --- |
| B001 | 请求与 preparation/generation 阶段、run/task/budget identity 双向核验；retained chain 消费全部候选请求，拒绝缺失或无来源的回执。前三个 preparation 请求另须落在 preparation trace 时间窗内。 |
| B002 | ledger/manifest 预算、启动 argv、provider-independent runtime 参数均严格绑定。summary 以阶段选择请求上限：contract/candidate 为 600 秒，evaluator compiler/auditor 为 900 秒；首合同请求改成 900 秒被拒绝。 |
| B003 | preparation/total wall、首次 terminal reason 及 monotonic trace 已核验；实际请求 elapsed 超出其 effective timeout 不获成功，trace 末尾不能晚于 guard/worker 终点，本地 holdout 继续受原总 deadline 约束。 |
| B004 | 首次 closure index/time/reason/摘要不可被第二次 close 改写，增删改 rows 或 token 派生值后的 close 不得修复冲突。 |
| B005 | canonical registration seal 与 Git 已提交文件清单绑定，修改 manifest 或引用文件、dirty/unpushed checkout、复用 root/slot 均被拒绝。 |
| B006 | unknown/failed holdout、非零 native/process exit、cleanup unknown 不能形成 joint success；匹配数量不能覆盖未知或失败 outcome。 |

本轮入口审查新增的问题与修复：

| 编号 | 原问题 | 已完成的离线修复与复验 |
| --- | --- | --- |
| B007 | retained `summarize()` 未调用原生 generation receipt 核验；孤立 mapper 通过不能证明实际结果绑定了 parser completion。 | `inspect_product()` 接入 `retained_chain` 和原生 trace，核验六阶段、完整源/输入/执行/评分/选择/交付、Store event 与实际请求。缺失、failed 或冲突证据保持零完成与 `0/1`。summary 不调用 runtime、候选或 evaluator；只读 archive 绕过具有恢复副作用的产品构造器，并拒绝 seed recovery 残留。 |
| B008 | `worker.main()` 将普通 CLI 文本输出重定向到 `xb` 二进制流，触发 `TypeError`。 | 改为 exclusive UTF-8 文本捕获；直接运行原生 CLI 的离线 worker 测试保留 JSON、native exit 和 terminal record，已有文件不覆盖。 |
| B009 | worker 已有 `holdout_gate` 失败阶段，summary allowlist 却未识别。 | summary 接受受限 `holdout_gate`。缺 primary completion、output artifact 或 source evidence 时零 holdout，失败可正常汇总，primary/joint 保持 `0/1`。 |
| B010 | preparation 已登记 900 秒，但共享请求 guard 仍按普通 600 秒截短 evaluator compiler/auditor。 | 请求 ceiling 按 thread-local 原生阶段切换，compiler/auditor 得到 900 秒上限；contract/candidate 继续 600 秒，总 deadline 仍可进一步收紧；并发上下文不互相借用时限。 |
| B011 | 早期 setup 失败可在没有 worker-started 的情况下留下 worker-finished，之后修好输入可能重启同槽。 | worker 入口在 provider 加载前拒绝任一已有 worker-started/worker-finished 或 root/slot finished；失败后的再次调用保留首次 terminal 字节并保持零新增请求。 |

独立复核还实际构造了三个 retained evidence 反例：把请求 effective timeout 改为 `1e-9`、
把 preparation trace 改为 `0→0` 而三次准备请求仍在其后、把本地阶段移到 worker 结束以后。
原实现曾错误成功，现均失去 primary/joint credit。首合同请求上限改为 900 秒的反例也已加入
阶段上限负测。原生 generation event 被删除或 task identity 被替换时，实际 summary 返回
零完成候选、primary/joint `0/1` 且保留树字节不变。

只读复核对 LocalController/CandidateArchive 构造器、seed recovery、provider、候选执行和
评分入口放置禁止调用的 sentinel，成功链仍能通过；seed recovery 残留被拒绝而不修复它。
审计使用私有 SQLite/WAL 副本，成功及失败路径均核对保留文件字节不变。曾在只读 adapter
重构中途出现的配置兼容失败已修正：允许既有 `command_sha256=None`，非空配置仍拒绝。

T007 已完成：当前 8409 passed / 1 skipped / 24 deselected（668.93s），固定 Feature 123
阶段 24 passed（22.92s），双阶段 overall exit0。最终静态检查和历史 inventories 通过，详见
[validation.md](validation.md)。全量启动后补充的 registration inventory 覆盖另经 18 项
registration_store 与静态/最终清单核验通过，不声称全量重新加载了该窄改动。
本次离线实现检查点没有具体 manifest、真实槽或 provider 请求。之后登记状态以
`measurement/manifest.json` 及只读启动检查为准，T008 核验保存在忽略的本地证据中；无需在
登记后改写本审计快照。

### 本次独立聚焦复验

```sh
.venv/bin/pytest -o addopts='' -q \
  tests/test_measurement139_retained_chain.py \
  tests/test_measurement139_registration.py tests/test_measurement139_stage_chain.py \
  tests/test_measurement139_public.py tests/test_measurement139_registration_store.py \
  tests/test_measurement139_observation.py tests/test_measurement139_worker.py
# 256 passed in 66.68s

.venv/bin/pytest -o addopts='' -q tests/test_measurement139_analysis.py \
  tests/test_measurement139_retained_chain.py::test_retained_native_closure_is_complete_and_read_only
# 35 passed in 57.78s
```

第二组包含最终按 stage 区分合同/候选 600 秒与 evaluator preparation 900 秒的 summary
负测，以及 effective timeout overrun 和 summary 单次发布/只读验证。两组有重叠，不合并为
唯一测试总数；它们也不替代 T007 的全量当前与固定历史阶段。

## 原始审查验证结果与边界（2026-09-19）

```sh
.venv/bin/pytest -o addopts='' -q \
  tests/test_measurement139_registration.py \
  tests/test_measurement139_stage_chain.py \
  tests/test_measurement139_public.py \
  tests/test_measurement139_native_receipts.py
```

结果为 **120 passed in 0.43s**，`git diff --check` 通过。120 项测试通过仅证明这些已有 fixture
通过；下列独立复现仍可违反登记/成功规则，所以不能据此宣布登记完成或允许真实运行。

## 原始审查时已确认修复的部分（2026-09-19）

| 项目 | 本次只读复验结果 | 实现定位 |
| --- | --- | --- |
| 登记输入绑定 | 在 manifest 保持不变时，execution 使用 `"9" * 64` 的错误 input digest 被 `execution_input_mismatch` 拒绝；交付继续绑定执行摘要。 | [campaign.py](measurement/campaign.py)，`candidate_execution()`，约 510–533 行 |
| 有效评分不可缺失 | `valid=True, score=None` 被 `evaluation_score_invalid` 拒绝；有效 score 必须为有限数值，selection 再次检查。 | [campaign.py](measurement/campaign.py)，`independent_scoring()` / `selection()`，约 535–575 行 |
| 零请求、pending、unknown 请求 | 替换为零请求、pending 或 unknown outcome ledger，primary/joint 均保持 `0/1`。未知 usage 继续为 null；这与未知 request outcome 不同。 | [campaign.py](measurement/campaign.py)，`RequestLedger.audit()` / `public_result()` |
| 请求重叠与请求超时 | 已有 pending 时再 `begin()` 被拒绝；单请求超时完成被记为 unknown 并关闭，`ledger_finalized=False`。failed/unknown 请求后不能正常申请新请求。 | [campaign.py](measurement/campaign.py)，`RequestLedger.begin()` / `finish()`，约 216–295 行 |
| 阶段乱序 | 将 holdout 移到 generation 之前，即使重算所有 receipt/hash chain 并更新合成 anchor，仍被 `receipt_order_mismatch` 拒绝。 | [campaign.py](measurement/campaign.py)，`ClosureCampaign.audit()`，约 626–674 行 |
| Feature 140 原生 generation receipt | 当前 [native_receipts.py](measurement/native_receipts.py) 已按 canonical Store event 核验 event ID、run/task/budget/candidate identity、登记工具上限及 bundle digest；旧瞬态 diagnostic 不再被当作完成证据。 | [test_measurement139_native_receipts.py](../../tests/test_measurement139_native_receipts.py) |

上述修复都不替代真实请求、固定预算和保留产物的绑定。特别是，固定 manifest 下的输入检查已
成立，但 manifest 自身可被修改的问题仍见 B005。

## 原始六项阻断与复验门槛（2026-09-19 快照）

### B001 — [P1] 完整成功仍只需要任意一个已完成普通请求

**定位**：[campaign.py](measurement/campaign.py) 的 `RequestLedger.audit()`（约 397–400 行）
和 `public_result()`（约 750–751 行）；
[measurement139_support.py](../../tests/measurement139_support.py) 的 `complete_campaign()`。

**复现**：现有 `complete_campaign()` 只登记一个 `request_kind="ordinary"` 请求，随后关闭
ledger；没有 preparation 请求、generation 请求或它们的 identity/digest 绑定，却能返回
`primary_success="1/1"`、`joint_success="1/1"`。

**原因与整改门槛**：成功 gate 只检查 ledger 非空、closed、所有请求 completed。request row
不含 native stage、run/task/budget、request digest，stage receipt 也不引用请求。需要由原生
observer 记录实际合同编译、evaluator compiler/auditor 和候选请求，并逐一绑定其阶段 receipt。
不能用“请求数至少为某常数”代替绑定：Agent loop 可有多个模型 turn，必须保留同一 generation
request/budget 归属且没有漏记、重复归属或无来源的完成声明。

**要求的负向回归**：只有一个无关请求；缺 compiler/auditor/generation 中任一请求；将别的
run/task/budget 请求放入台账；同一请求重复支持不相容阶段。均不得产生 primary/joint `1/1`。

### B002 — [P1] ledger 的实际策略没有绑定 manifest 的登记预算

**定位**：[campaign.py](measurement/campaign.py) 的 `ClosureCampaign.__post_init__()`
（约 447–452 行）、`audit()`（约 671 行）和 `RequestLedger.audit()`。

**复现**：在成功合成 campaign 中替换 ledger 为
`RequestLedger(wall_seconds=10000, max_requests=100, token_stop_threshold=1000000)`；
令请求在 `t=9000` 开始、`t=9100` completed，观测 `200000` tokens，再关闭。manifest 仍固定
`2400` 秒、`20` 请求和 `160000` tokens，public primary/joint 却仍为 `1/1`。

**原因与整改门槛**：audit 只校验 ledger 相对于自身配置是否合法。须将 ledger 规则与不可变
registration 的 max requests、request kind/timeout、token stop、preparation wall 和 total
wall 精确绑定，在构造、恢复读取及公开 projection 前拒绝不一致；不能信任替换后的对象配置。

**要求的负向回归**：分别扩大 request count、wall、token threshold、ordinary/preparation
timeout，且构建在扩容条件下自洽的 ledger。即使 ledger 自身 audit 通过，campaign 仍须拒绝。

### B003 — [P1] 总墙钟终止被当作成功关闭，准备总墙钟未被审计

**定位**：[campaign.py](measurement/campaign.py) 的 `RequestLedger.begin()`
（约 228–230 行）、`_close()`（约 212–214 行）及 `audit()` 的 `ledger_finalized`
（约 397–400 行）。stage receipt 当前没有时间字段。

**复现一**：先正常完成一个请求，再调用 `begin(now=2400)`。调用抛出
`attempt_deadline_reached`，但由于此前请求均 completed，`audit()["ledger_finalized"]`
仍为 True；配合完整合成阶段链，primary/joint 仍为 `1/1`。

**复现二**：依次登记 preparation 请求，时间为 `0→900`、`901→1801`、`1802→1900`，随后
close。每次请求小于 900 秒且在 total wall 内，因此 audit 接受，尽管 preparation 已超过
登记的 1860 秒。

**原因与整改门槛**：只有 `closed_at_index`，没有首次关闭原因、关闭时间或整次运行的 terminal
状态；请求范围之外的执行、评分、交付、holdout、cleanup 时间也不可验证。需要同一单调时钟
贯穿全阶段、保存 preparation 起止和 campaign 起止/预算结果，并区分正常完成、预算终止、
失败、unknown。预算耗尽不能只因先前请求 completed 而提升为成功。

**要求的负向回归**：最后模型请求后 total wall 到期；请求前 total wall 到期；preparation
请求均各自按时但总准备超时；本地执行/评分/交付/holdout 超出总墙钟；终止时仍有 pending。
这些路径应保留可审计的终态证据，并保持 primary/joint 与规范一致。

### B004 — [P1] 重复 close 可以覆盖首次关闭位置

**定位**：[campaign.py](measurement/campaign.py) 的 `RequestLedger.close()`
（约 297–300 行）及 `_close()`（约 212–214 行）。

**复现**：正常关闭成功 ledger 后，在内存合成 retained rows 中追加一条 completed post-slot
row，并同步 known token sum。第一次 audit 因 `closed_at_index` 与 rows 长度不符而拒绝；
再次调用 `close()` 会把 `closed_at_index` 改为新长度，audit 随即通过，public primary 为
`1/1`。这是对 retained 数据篡改的审计复现，不涉及真实请求。

**原因与整改门槛**：close 会无条件覆盖首次关闭锚点。首次关闭的 index/time/reason 应持久化且
不可变；重复调用只可对完全相同状态幂等成功，否则拒绝，不能替后续 rows 重新生成关闭证明。

**要求的负向回归**：显式 close 后添加/删改 rows；terminal outcome 后再次 close；首次关闭
后变更 token 派生值或关闭理由。后续 close 不得修复这些冲突。

### B005 — [P1] mutable manifest 可改变输入和分母，public 仍硬编码一槽

**定位**：[campaign.py](measurement/campaign.py) 的 `ClosureCampaign.__post_init__()`
（约 447–452 行）、`audit()`（约 673 行）和 `public_result()`（约 750、759–760 行）。

**复现**：构建 campaign 后修改 `c.manifest["input_sha256"] = "9" * 64` 和
`c.manifest["planned_attempts"] = 2`，再按修改后的 input 建立完整链。audit 返回
`one_attempt=False`，但 public 的 `planned_attempts/attempts` 都硬编码为 1，primary/joint
仍为 `1/1`。

**原因与整改门槛**：构造时复制/验证一次不是不可变登记；后续没有核验 manifest 摘要，成功
判定也忽略 `one_attempt`。须冻结并验证 canonical registration hash、身份、任务/输入、
预算及分母。public 分母应由验证后的登记得出，登记变化应明确拒绝，不能被硬编码掩盖。

**要求的负向回归**：构造后修改 input/task、planned attempts、retries、holdouts、provider、
root 或 budget；调用 record、audit 和 public projection 均不能让修改后的登记获得成功。

### B006 — [P1] unknown holdout 仍可获得 joint success

**定位**：[campaign.py](measurement/campaign.py) 的 `public_result()`（约 754–755 行）。

**复现**：六个主阶段合法成功后调用
`record("holdouts", outcome="unknown", delivery_receipt_sha256=正确摘要,
matched_count=8, total=8, results=八项 matched=True)`，再记录 `cleanup(verified=True)`。
audit 通过，public 显示 `stages.holdouts="unknown"`，但 `joint_success="1/1"`。

**原因与整改门槛**：joint 只检查匹配数量及 cleanup，遗漏 holdout outcome。joint 必须要求
holdout receipt 本身成功、八项 expected/actual 绑定有效、没有 unknown/pending stage，且
native/process exit 和 cleanup 都有已验证证据。

**要求的负向回归**：unknown/failed holdout 带 8/8 数据；holdout 缺少执行或产物证据；cleanup
unknown；native/process 非零退出。匹配数量不能覆盖失败或未知状态。

## 真实 preregistration 前必须完成的 gate

以下 gate 是对 [spec.md](spec.md)、[plan.md](plan.md)、[tasks.md](tasks.md) 的落地检查，
不是另一个运行许可。其中实现、离线入口和 T007 验证已完成，要求保留供后续核验；本次
检查点仍需在 T008 独立核验具体登记和唯一运行槽。

1. **冻结真正要运行的产品和任务。** 固定包含 Feature 140/141 所需行为的已推送产品版本；
   当前 [case.py](measurement/case.py) 的离线产品引用 `87d86d9` 和 synthetic task 不可直接
   代替最终真实 registration。固定原生入口、runtime/provider/model 身份、候选工具上限、
   population/seed、输入、受支持的 evaluator/八项 holdout、request/preparation/total wall
   和 source/artifact 限制。若 evaluator 是自动生成的，登记其生成/冻结协议及身份验收规则，
   运行中再保留实际 frozen evaluator/profile 摘要，不预填未产生的产物摘要。
2. **复核已实现的 registration/preflight，并冻结具体 manifest。** pin 产品、measurement/spec、运行时与
   历史证据的完整文件集合/大小/SHA；核验 clean worktree、真实 `HEAD == origin/main`、已提交
   并推送的 manifest、运行产品与 pin 一致。实际检查唯一新 ID、root/attempt 不存在，不能用
   调用方传入的默认布尔值或空集合证明这些事实。
3. **完成已实现的持久唯一槽、worker、observer、supervision 的入口验收。** 原子创建未使用 campaign/attempt，
   durable 写入 started/finished/terminal；进程失败、重启或中断后不能 retry/resume/replace
   该槽。所有 provider 请求均由统一 admission 路径计数并绑定身份，记录未知请求而不丢弃。
4. **完成请求与原生六阶段的双向绑定。** 接入
   [native_receipts.py](measurement/native_receipts.py)，把原生 Store 的 generation event ID、
   run/task/budget/candidate/source identity 和每个模型 turn/request digest 对齐；验证实际
   preparation、execution、score、selection、parent delivery 的 native receipts。每个
   必需阶段均有来源，每个请求均归属同一登记/槽，后续产物不能补造缺失前置证据。
5. **证明全部预算真正生效。** 修复 B002–B004；固定的普通 600 秒、准备请求 900 秒、准备
   总墙钟 1860 秒、全程 2400 秒、20 请求、160000 observed-token stop、12 candidate steps
   和 holdout 时间均通过实际配置、native receipt 和同一 monotonic timeline 验证。保留
   首次关闭原因/时间以及本地监督进程的 deadline/cleanup 证据。
6. **从保留产物独立验证成功。** 只读检查原生 source bundle、registered input、execution
   snapshot/output、prepared evaluator、typed score/check report、validity-first selection、
   parent publication package 和 reciprocal links。重算实际文件摘要、大小和完整集合；验证
   native/process exit、8/8 holdout expected/actual 及 cleanup。内存 boolean 或一段合法
   SHA 字符串不等于产物证明；不在 summarize/audit 中重跑 provider 或生成源码。
7. **关闭原始阻断及入口集成缺口并完成最终验证。** 复验 B001–B006 失败回归，完成 B007–B011
   的真实 retained summary/worker 入口离线集成，运行聚焦集、当前全量回归、
   固定历史阶段、Ruff、compileall、Specify 和 diff 检查；独立复核 Feature 131/134 retained
   文件集合、大小和 SHA 未变。T007 已记录最终命令/计数和审计结论；具体产品 pin 与
   manifest hash 留待 T008 冻结并核验。未通过登记及启动 gate 前，T009 不得启动。

## 后续交接定位

campaign-local evidence/ledger/success gate、真实 harness 入口与 T007 已完成离线验收。
当前剩余为 T008 的具体登记与启动核验及之后唯一真实槽；如果后续发现共享产品缺口，应
另开产品 SDD，不能在测量运行后修补产品或改登记。Feature 131/134、WebAgent 及其历史分母
保持不变。

本次复核按 B001–B011 及时间关联负测逐项检查实现和实际入口，不以测试数量增长代替关闭
判定。未来代码变更仍须复验；本次离线关闭不使正式 registration、唯一真实运行或真实闭环
验收自动完成。
