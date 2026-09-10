"""Render a validated two-slot corrected workflow observation without dispatch."""
import argparse
import json
import math
from pathlib import Path

CASES = {"sheet_metal_nesting": "钣金套料", "china_post_pickup_optimization": "邮政揽收优化"}
STATUSES = {"not_started": "待启动", "started_unresolved": "运行中／未决", "failed": "失败",
            "completed": "完成", "terminated_without_accepted_report": "终止／无已接受报告"}


def require(condition):
    if not condition:
        raise ValueError("invalid corrected-workflow report evidence")


def number(value):
    if value is None:
        return "null"
    require(type(value) in (int, float) and math.isfinite(value))
    return str(value)


def render_report(audited):
    summary, stages = audited["summary"], audited["stages"]
    require(audited["passed"] is True and audited["manifest_sha256"] == summary["manifest_sha256"])
    rows = summary["slots"]
    require(summary["planned_attempts"] == 2 and len(rows) == len(stages) == 2)
    require([r["index"] for r in rows] == [1, 2] and {r["case_key"] for r in rows} == set(CASES))
    require(all(type(row["process_terminated"]) is bool for row in rows)
            and summary["all_slots_terminated"] is all(row["process_terminated"] for row in rows))
    require(not audited["complete"] or summary["all_slots_terminated"] is True)
    require(not audited["final_acceptance"] or audited["complete"] is True)
    lines = ["# Lunar Agent 修复后分阶段评测", "",
             "状态：" + ("两个尝试已终止，结果审计通过。" if audited["complete"] else "进行中，结果仍未决。"), "",
             "GLM-5.2，Master上限1200秒，共享总预算5400秒 / 200工具 / 800万累计tokens。", "",
             "| Case | 状态 | 计划验收 | 进入Build | 续跑 | Validity | Overall | Quality |",
             "| --- | --- | --- | --- | --- | ---: | ---: | ---: |"]
    for row, stage in zip(rows, stages, strict=True):
        require(row["index"] == stage["index"] and row["arm"] == "S"
                and row["budget_arm"] == stage["budget_arm"] == "master_1200")
        require(stage["master_duration_seconds"] is None)
        require(type(stage["plan_record_valid"]) is bool and type(stage["build_entered_observed"]) is bool
                and (not stage["build_entered_observed"] or stage["plan_record_valid"]))
        if not row["harness_receipt_accepted"] or row["extraction_status"] != "completed":
            require(all(row[key] is None for key in ("validity_score", "overall_score", "quality_score")))
        scores = " | ".join(number(row[key]) for key in ("validity_score", "overall_score", "quality_score"))
        resume = "null" if stage["resume_used"] is None else "是" if stage["resume_used"] else "否"
        lines.append(f"| {CASES[row['case_key']]} | {STATUSES[row['status']]} | "
                     f"{'是' if stage['plan_record_valid'] else '未观察到'} | "
                     f"{'是' if stage['build_entered_observed'] else '未观察到'} | {resume} | {scores} |")
    require(set(summary["budget_arms"]) == {"master_1200"})
    group = summary["budget_arms"]["master_1200"]
    valid = sum(r["harness_receipt_accepted"] and r["validity_score"] is not None
                and r["validity_score"] > 0 and r["overall_score"] is not None for r in rows)
    expected = {"planned": 2, "valid": valid, "valid_solution_rate": valid / 2,
                "started": sum(r["started"] for r in rows),
                "terminated": sum(r["process_terminated"] for r in rows),
                "subject_receipts": sum(r["subject_receipt_accepted"] for r in rows),
                "accepted_harness_receipts": sum(r["harness_receipt_accepted"] for r in rows)}
    require(all(group[key] == value for key, value in expected.items()))
    lines += ["", f"固定分母2；已终止{group['terminated']}；已观察有效解{valid}。",
              "null是未知或未评分，不能当作零分；计划/Build/checkpoint不等于有效解。",
              "Master精确耗时未记录，保持null；失败完整用量和费用未知时同样保持null。",
              "每个case只有一次新尝试，历史样本不进分母，不跨case合并质量均值，也不声称修复因果效果。",
              "本报告不检查操作系统进程存活，最终封存另有进程核对。",
              f"预注册SHA256：`{audited['manifest_sha256']}`。", ""]
    if not audited["complete"]:
        lines.insert(-1, "运行中或未启动槽仍未决，上述计数不是最终失败率。")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", type=Path, help="saved successful read-only audit")
    args = parser.parse_args()
    print(render_report(json.loads(args.audit.read_bytes())), end="")


if __name__ == "__main__":
    main()
