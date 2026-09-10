"""Render only a successful budget campaign audit; no candidate execution or scoring."""
import argparse
import math
from pathlib import Path
from types import ModuleType

CASES = {"sheet_metal_nesting": "钣金套料", "china_post_pickup_optimization": "邮政揽收优化"}
STATUSES = {"not_started": "待启动", "started_unresolved": "运行中／未决", "failed": "失败",
            "completed": "完成", "terminated_without_accepted_report": "终止／无已接受报告"}


def require(condition):
    if not condition:
        raise ValueError("invalid report evidence")


def number(value):
    if value is None:
        return "null"
    require(type(value) in (int, float) and math.isfinite(value))
    return str(value)


def render_report(audited):
    require(audited["passed"] is True)
    summary = audited["summary"]
    require(summary["manifest_sha256"] == audited["manifest_sha256"] and summary["planned_attempts"] == 4)
    require(len(summary["slots"]) == len(audited["stages"]) == 4)
    complete = audited["complete"]
    require(not complete or summary["all_slots_terminated"] is True)
    lines = ["# Lunar Agent Master 预算对照", "",
             "状态：" + ("四次尝试已终止，结果审计通过。" if complete else "进行中，尚不能作最终比较。"), "",
             "同一 GLM-5.2、工具与输入；Master 上限 300/1200 秒，总预算均为 5400 秒 / 200 工具 / 800 万 tokens。", "",
             "| Case | Master 上限 | 状态 | 计划记录有效 | 观察到 Build | Validity | Overall | Quality |",
             "| --- | ---: | --- | --- | --- | ---: | ---: | ---: |"]
    for row, stage in zip(summary["slots"], audited["stages"], strict=True):
        require(row["index"] == stage["index"] and row["budget_arm"] == stage["budget_arm"])
        require(stage["master_duration_seconds"] is None)
        require(type(stage["plan_record_valid"]) is bool and type(stage["build_entered_observed"]) is bool
                and (not stage["build_entered_observed"] or stage["plan_record_valid"]))
        if not row["harness_receipt_accepted"] or row["extraction_status"] != "completed":
            require(all(row[key] is None for key in ("validity_score", "overall_score", "quality_score")))
        scores = " | ".join(number(row[key]) for key in ("validity_score", "overall_score", "quality_score"))
        lines.append(f"| {CASES[row['case_key']]} | {row['budget_arm'].removeprefix('master_')} 秒 | "
                     f"{STATUSES[row['status']]} | {'是' if stage['plan_record_valid'] else '未观察到'} | "
                     f"{'是' if stage['build_entered_observed'] else '未观察到'} | {scores} |")
    lines += ["", "| Master 上限 | 固定分母 | 已终止 | 已观察有效解 |",
              "| --- | ---: | ---: | ---: |"]
    for arm in ("master_300", "master_1200"):
        group = summary["budget_arms"][arm]
        require(group["planned"] == 2)
        rows = [row for row in summary["slots"] if row["budget_arm"] == arm]
        require(len(rows) == 2 and group["terminated"] == sum(row["process_terminated"] for row in rows)
                and group["valid"] == sum(row["harness_receipt_accepted"]
                    and row["validity_score"] is not None and row["validity_score"] > 0
                    and row["overall_score"] is not None for row in rows))
        lines.append(f"| {arm.removeprefix('master_')} 秒 | 2 | {group['terminated']} | {group['valid']} |")
    lines += ["", "null 表示没有可用评分，不能当作零分；费用与失败完整用量未知时同样保留 null。",
              "Master 精确耗时未记录，保持 null；长预算组成功交接也不能证明计划一定用了超过 300 秒。",
              "计划验收或进入 Build 不等于有效解。每个 case/预算仅一次，不能证明普遍充分性或稳定成功率。",
              "历史 069 结果仅作背景，不进入本批分母；不同 case 不合并质量均值。",
              "2400 秒 Build 边界是完整工具轮次后的合作式 checkpoint；续跑共享剩余总预算。",
              "结果审计不检查操作系统进程存活，最终封存还需独立进程终止核对。",
              f"预注册 SHA256：`{audited['manifest_sha256']}`。", ""]
    if not complete:
        lines.insert(-1, "运行中与待启动槽仍未决，已观察有效解数量不是最终失败率。")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    path = here / "audit.py"
    module = ModuleType("report072_audit")
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)  # noqa: S102
    adapter, _ = module.dependencies()
    audited = module.audit_registered_campaign(module.MEASUREMENT / "manifest.json", adapter.CAMPAIGN,
                                               require_complete=args.require_complete)
    print(render_report(audited), end="")


if __name__ == "__main__":
    main()
