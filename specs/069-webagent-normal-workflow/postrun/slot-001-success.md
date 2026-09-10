# 首波钣金普通流程：真实成功结果

观测于2026-09-10 11:14 +0800。Slot 1 的唯一新 attempt 已完成：独立 exact harness
给出 validity=1、overall=quality=0.999999，extraction_status=completed。
这是一份已验收的成功结果；整个四槽 campaign 仍在进行中。

| 项目 | 原始观测 | 口径 |
| --- | ---: | --- |
| Subject 耗时 | 3068.032 秒 | subject phase termination marker |
| Harness 耗时 | 122.493 秒 | harness phase termination marker |
| Native run 耗时 | 3190.563 秒 | native record 的 elapsed_ms=3190563 |
| 输入 tokens | 719940 | subject receipt，完整累计 |
| 输出 tokens | 149337 | subject receipt，完整累计 |
| 总 tokens | 869277 | subject receipt，不含 extractor |
| 模型交互 | 30 | subject receipt，不是工具调用次数 |
| 费用 | null | 未配置单价，不能解释为免费 |

Subject requested/effective model 均为 glm-5.2，model_evidence=provider_observed；profile
SHA 为 da362bcb878a675f2c92dab88d022cfa40f6ef95db54871deb8f71e481c4968b。
Subject 和 harness 进程均退出0。Subject receipt 不含分数；上述三个分数来自已验收的
harness receipt。原始 benchmark 为 famou-bench 1.10.6，case revision/publication、
extractor 和 evaluator 的实际字节均与预注册一致。

只读审计与独立审阅已核对 request/public projection、subject/harness receipt、native
record/control-state/report、worker outcome/termination 的完整绑定，以及唯一
`runs/001/attempts/001`。审阅没有执行候选、模型或 harness，也没有改变原始证据。

Slot 3（钣金分阶段）和 slot 4（邮政普通）于11:12:53 +0800自动启动。外层开始时间加
elapsed 推算的第一波最晚结束与第二波启动相差约0.056秒，符合原调度屏障；这仍采用
审计器已披露的时间一致性口径，不能当作精确逐调用计时。两例在本观测时尚未决。

本次钣金分数与 Feature 068 的 Lunar 0.999999 相同，也处于该 case 历史平台
0.996101 / 0.999999 / 0.999999 的高分范围。它再次证明普通流程能在这个高分 case
交付有效解；历史样本不计入本批分母，不能据此判断未结束的 staged 对照或整体框架优劣。

证据索引：

- 实际partial审计：[20260910T031419Z.json](observations/20260910T031419Z.json)，
  SHA256 `f31392c1d85afb014028465ee445dacaf0108470e41ba1eaf5b22944d4ede408`。
- 对应中文报告：[20260910T031419Z.md](observations/20260910T031419Z.md)。
- Native record SHA256：`e8b93b8442474292833a125a60dc0a183318c0d5726155b75feebc339834a6c6`。
- Native report SHA256：`e2251171dca09a431b2bbca55e6285ae8948edf134139da9060c713c98a5b866`。

快照中的185项证据SHA包括上述原生回执与phase markers，冻结源码37项、执行/输入/测试
74项及历史锚点8项保持原样。本轮无产品代码变化，不重复全仓测试。
