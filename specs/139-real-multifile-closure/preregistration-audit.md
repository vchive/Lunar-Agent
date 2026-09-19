# Feature 139 预登记独立审计

**日期**：2026-09-19
**结论**：尚不具备真实 preregistration 条件；六项剩余阻断必须先修复并复验。
**检查基线**：`HEAD=741900a1c8068d31094c25d27b1e4c7397b1dbb0` 加本轮未提交的
Feature 139 campaign/ledger 加固。下列行号对应此次审查快照，后续以函数名和阻断编号定位。

本审查只读取实现、执行内存合成复现和离线聚焦测试；未登记、启动 campaign、调用 provider，
也未执行历史生成源码。Feature 141 的产品验证由主线程独立进行，不属于本审查的完成证明。
本文是整改依据，不是 registration、launch approval 或真实端到端成功报告。

## 验证结果与边界

```sh
.venv/bin/pytest -o addopts='' -q \
  tests/test_measurement139_registration.py \
  tests/test_measurement139_stage_chain.py \
  tests/test_measurement139_public.py \
  tests/test_measurement139_native_receipts.py
```

结果为 **120 passed in 0.43s**，`git diff --check` 通过。120 项测试通过仅证明这些已有 fixture
通过；下列独立复现仍可违反登记/成功规则，所以不能据此宣布登记完成或允许真实运行。

## 前次问题中已确认修复的部分

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

## 六项剩余阻断

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
不是另一个运行许可。通过离线 fixture 后仍需独立核验具体登记和唯一运行槽。

1. **冻结真正要运行的产品和任务。** 固定包含 Feature 140/141 所需行为的已推送产品版本；
   当前 [case.py](measurement/case.py) 的 Feature 138 产品 pin 和 synthetic task 不可直接
   代替最终真实 registration。固定原生入口、runtime/provider/model 身份、候选工具上限、
   population/seed、输入、受支持的 evaluator/八项 holdout、request/preparation/total wall
   和 source/artifact 限制。若 evaluator 是自动生成的，登记其生成/冻结协议及身份验收规则，
   运行中再保留实际 frozen evaluator/profile 摘要，不预填未产生的产物摘要。
2. **实现并复核具体 manifest 和启动 preflight。** pin 产品、measurement/spec、运行时与
   历史证据的完整文件集合/大小/SHA；核验 clean worktree、真实 `HEAD == origin/main`、已提交
   并推送的 manifest、运行产品与 pin 一致。实际检查唯一新 ID、root/attempt 不存在，不能用
   调用方传入的默认布尔值或空集合证明这些事实。
3. **实现持久唯一槽、worker、observer、supervision。** 原子创建未使用 campaign/attempt，
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
7. **关闭六项阻断并完成最终验证。** 为 B001–B006 添加失败回归，运行聚焦集、当前全量回归、
   固定历史阶段、Ruff、compileall、Specify 和 diff 检查；独立复核 Feature 131/134 retained
   文件集合、大小和 SHA 未变。记录最终命令/计数、产品 pin、manifest hash、审计结论，再进入
   T008。未通过这些 gate 前，T009 不得启动。

## 后续交接定位

当前整改范围首先是 campaign-local evidence/ledger/success gate（B001–B006）及真实 harness
落地；如果发现共享产品无法提供所需原生证据，应按计划另开产品 SDD，不能在测量运行后修补
产品或改登记。Feature 131/134、WebAgent 及其历史分母保持不变。

整改后的复查应逐项标明 B001–B006 的新测试、实现位置和证据，不以测试数量增长代替关闭
判定。本文记录的是本次未提交快照的审查结果；后续修复提交不会自动使本文结论变为通过。
