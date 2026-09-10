# Feature 069：四次真实评测结果

2026-09-10 12:09:16 +0800，四个预注册尝试全部结束。普通流程在两个case上均得到独立
评分器认可的有效解；分阶段流程两次均在Master的300秒截止点失败，未进入Build或续跑。

| Case | 流程 | Validity | Overall / Quality | Subject耗时 | Harness耗时 |
| --- | --- | ---: | ---: | ---: | ---: |
| 钣金套料 | 普通M | 1 | 0.999999 | 3068.032秒 | 122.493秒 |
| 钣金套料 | 分阶段S | null | null | 300.222秒 | 未运行 |
| 邮政揽收优化 | 普通M | 1 | 1.0185 | 3331.589秒 | 50.244秒 |
| 邮政揽收优化 | 分阶段S | null | null | 300.255秒 | 未运行 |

M固定分母2，有效2/2，接受subject/harness回执各2份；S固定分母2，有效0/2，无可接受回执。
每个case/流程只有一次尝试，失败未补位，没有重启或替换样本。未知分数保留null，不能
当作质量零分；1.0185来自原始harness回执，未裁剪到1，也没有跨case计算平均分。

两例普通流程的requested/effective model均为glm-5.2，model_evidence=provider_observed。
钣金subject有30次模型交互，input719940/output149337/total869277 tokens；邮政有59次，
input2010306/output138981/total2149287。以上是subject完整累计用量，不包括extractor。
S两次完整用量仍未知，初始workflow零计数不代表零消费。所有费用为null，未配置单价。

## 可以得出的结论

Lunar普通流程确实能在用户指定的两类WebAgent历史高分case上交付有效解。钣金本次分数
与上一批Lunar的0.999999相同；邮政上一批超时无分数，本次得1.0185。已有平台三次分数
分别为钣金0.996101 / 0.999999 / 0.999999、邮政1.0164 / 0.7973 / 0.9938，仅作描述性背景，
不进入本批分母。这些观测不能证明单次运行稳定必成，也不能证明整体框架优于历史平台。

本次staged配置未观察到交付收益：两个Master都没有成功返回并持久化最终计划，随后
因model/timeout终止，尚未进入JSON计划验收、Build或续跑。因此不能用本次0/2评价
续跑后的求解质量，也不能认为放宽计划解析即可修复失败。工具错误后存在自主纠正；
缺少逐调用耗时，无法区分网络、排队、生成及数据探查耗时，不能把超时归因于单一工具。
具体行为见[Master分析](master-behavior-analysis.md)。

普通流程继续作为默认交付路径。先合入已独立验证的UTF-8预览边界和嵌套argv字符串
诊断修复，再以独立SDD定义更明确的规划职责、最小交接及有限探查范围。这个方向仍需
新实验检验；本次结果不授权修改历史manifest、回填分数或继续已失败的attempt。

## 封存与复核

预注册提交为`454b52118a85e1e5b04bae86cf231cfefe6b9524`，测量产品源码始终保持
`80f5af10f4a25dab5c5aa2ad767e3b78994f34a3`。两波并发2，每例各一次M/S，均GLM-5.2、
5400秒/200工具/800万tokens。真实运行使用已授权CC Switch环境，没有新provider探测、
WebAgent执行、平台数据请求或历史候选复制。

在修复集成前运行只读审计的`--require-complete`，已得到passed=true、complete=true、
final_acceptance=true，核对212项证据。检查包含原生receipt/record/state/report/outcome、
真实private case/extractor/evaluator字节、public projection、唯一attempt、wave顺序，以及
37项源码、74项冻结执行/输入/测试文件和8项历史锚点。审计不执行评分或恢复记录。

- 最终审计：[final-audit.json](final-audit.json)，SHA256
  `3175509fe7d2df7210047ec956ad2f24049189524adfe5670586704ec6cdb2e7`。
- 原生summary SHA256：`712e78755f61ce360a3249abe29624ec9aef291936b7209adba075d18938d450`。
- 生成报告：[final-report.md](final-report.md)，SHA256
  `b5c615539444985dfa28bb9fc1ab04908fd91b361421dbe14f2aa2dfaabe2a97`。

最终分数、失败分母与212项原始证据已经独立复核通过；另行检查已知PID/PGID和可见进程
参数/cwd未发现关联本批的残留，见[final-process-check.json](final-process-check.json)。该
检查保留未知child PID和无法关联脱离进程等限制，独立于上述SHA审计。后续源码
变化会使此旧批次的当前源码冻结检查拒绝通过，这是预期行为；保留封存结果与原Git锚点，
不改旧manifest来适配修复后的实现。
