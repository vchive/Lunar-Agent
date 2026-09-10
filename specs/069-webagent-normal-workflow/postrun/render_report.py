"""Render audited measurement observations; stdout only, with no subject or harness dispatch."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
MEASUREMENT = HERE.parent / "measurement"
CAMPAIGN = REPO / ".lunar/real-eval-glm-5.2-staged-20260910"
CASE_NAMES = {"sheet_metal_nesting": "钣金套料", "china_post_pickup_optimization": "邮政揽收优化"}
ARM_NAMES = {"M": "普通 control", "S": "分阶段 staged"}
STATUS_NAMES = {
    "not_started": "尚未启动", "started_unresolved": "运行中／结果未决", "failed": "失败",
    "completed": "流程完成", "terminated_without_accepted_report": "已终止，缺少可接受报告",
}


def require(condition):
    if not condition:
        raise ValueError("report evidence validation failed")


def number(value):
    if value is None:
        return "null"
    require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value))
    return str(value)


def validate_reference(reference, manifest, *, repo=REPO):
    """Reference is a derived projection; validate it against the already frozen original records."""
    require(reference["authority"] == "descriptive_only"
            and reference["historical_attempts_in_denominator"] == 0)
    paths = reference["source_files_sha256"]
    expected_paths = {
        ".lunar/high-score-case-selection-20260909/baseline-audit.json",
        ".lunar/real-eval-glm-5.2-high-score-20260909/summary.json",
    }
    require(set(paths) == expected_paths)
    for relative, digest in paths.items():
        path = repo / relative
        require(path.is_file() and not path.is_symlink())
        require(hashlib.sha256(path.read_bytes()).hexdigest() == digest
                == manifest["historical_files_sha256"][relative])
    selection = json.loads((repo / ".lunar/high-score-case-selection-20260909/baseline-audit.json").read_bytes())
    previous = json.loads((repo / ".lunar/real-eval-glm-5.2-high-score-20260909/summary.json").read_bytes())
    require(reference["model"] == selection["model"] == "glm-5.2")
    require(reference["platform"] == {
        "experiment_id": selection["experiment_id"], "agent_family": selection["agent_family"],
        "exact_agent_commit": None,
    })
    require(reference["prior_lunar_campaign"] == previous["campaign_id"])
    require(set(reference["cases"]) == set(CASE_NAMES))
    for key, case in reference["cases"].items():
        require(case["platform_runs"] == [
            {"source_run_index": row["run_index"], "validity_score": row["validity_score"],
             "overall_score": row["overall_score"]}
            for row in selection["by_case"][key]["runs"]
        ])
        old = next(row for row in previous["attempts"] if row["case_key"] == key)
        fields = ("status", "subject_receipt_accepted", "harness_receipt_accepted", "extraction_status",
                  "validity_score", "overall_score", "quality_score", "subject_elapsed_seconds")
        require(case["prior_lunar"] == {name: old[name] for name in fields})


def render_report(audited, reference):
    require(audited["passed"] is True)
    summary = audited["summary"]
    require(audited["manifest_sha256"] == summary["manifest_sha256"] == reference["manifest_sha256"])
    require(summary["planned_attempts"] == 4 and len(summary["slots"]) == 4)
    rows = summary["slots"]
    started = sum(row["started"] for row in rows)
    terminated = sum(row["process_terminated"] for row in rows)
    complete = audited["complete"]
    require(not complete or terminated == 4)
    lines = ["# Lunar Agent 分阶段流程评测", "",
             (f"状态：{'已完成并通过结果审计' if complete else '进行中，尚不能作最终比较'}；"
             f"计划 4 次，已启动 {started} 次，已终止 {terminated} 次。"), "",
             "每例各运行一次普通流程和分阶段流程；GLM-5.2，5400 秒 / 200 工具调用 / 800 万 tokens。", "",
             "| Case | 流程 | 状态 | Validity | Overall | Quality |",
             "| --- | --- | --- | ---: | ---: | ---: |"]
    for row in rows:
        # The auditor supplies the native accepted projection. Reject any accidental score fill.
        if not row["harness_receipt_accepted"] or row["extraction_status"] != "completed":
            require(all(row[key] is None for key in ("validity_score", "overall_score", "quality_score")))
        values = " | ".join(number(row[key]) for key in ("validity_score", "overall_score", "quality_score"))
        lines.append(f"| {CASE_NAMES[row['case_key']]} | {ARM_NAMES[row['arm']]} | "
                     f"{STATUS_NAMES[row['status']]} | {values} |")
    lines += ["", "`null` 表示没有可用评分，不能当作质量零分。候选文件或 checkpoint 不等于有效解。", "",
              "| 流程 | 固定分母 | 已接受 subject 回执 | 已接受 harness 回执 | 已观察有效解 |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for arm in ("M", "S"):
        item = summary["arms"][arm]
        require(item["planned"] == 2)
        lines.append(f"| {ARM_NAMES[arm]} | 2 | {item['subject_receipts']} | "
                     f"{item['accepted_harness_receipts']} | {item['valid']} |")
    if not complete:
        lines += ["", "运行中和排队中的槽仍未决；上表的已观察有效解数量不是最终失败率。"]
    lines += ["", "## 已有记录，仅作背景", "",
              "| Case | 平台 3 次 Overall | 上一批 Lunar Overall | 上一批 Lunar 状态 |",
              "| --- | --- | ---: | --- |"]
    for key, label in CASE_NAMES.items():
        item = reference["cases"][key]
        scores = " / ".join(number(row["overall_score"]) for row in item["platform_runs"])
        prior = item["prior_lunar"]
        lines.append(f"| {label} | {scores} | {number(prior['overall_score'])} | "
                     f"{STATUS_NAMES[prior['status']]} |")
    lines += ["", "历史记录不进入本批分母；平台已证明的是 AgentServer/OpenCode 家族，未绑定特定 v2.5 commit。",
              "不同 case 的分数不合并均值；每个 case/流程只有一次尝试，不能据此宣称整体框架优劣。",
              "分阶段流程同时改变规划、提示、历史与输出契约，差异不能单独归因于续跑。", "",
              f"预注册 SHA256：`{summary['manifest_sha256']}`。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("lunar_postrun_audit", HERE / "audit.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    audited = module.audit_registered_campaign(
        MEASUREMENT / "manifest.json", CAMPAIGN, require_complete=args.require_complete,
    )
    reference = json.loads((HERE / "reference.json").read_bytes())
    manifest = json.loads((MEASUREMENT / "manifest.json").read_bytes())
    validate_reference(reference, manifest)
    print(render_report(audited, reference), end="")


if __name__ == "__main__":
    main()
