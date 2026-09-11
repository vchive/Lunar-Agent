"""Render current native acceptance and advisory terminal diagnostics, preserving nulls."""
import argparse
import json
from pathlib import Path
from types import ModuleType


def _load_adapter():
    path = Path(__file__).resolve().parent.parent / "measurement/adapter.py"
    module = ModuleType("report082_adapter")
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)  # noqa: S102
    return module


_adapter = _load_adapter()


def render_report(audited):
    if (audited.get("kind") != "feature082_postrun_audit"
            or audited.get("implementation_commit") != _adapter.IMPLEMENTATION):
        raise ValueError("wrong HTTP deadline audit identity")
    prior = _adapter.load_previous_postrun("render_report")
    text = prior.render_report(audited)
    text = text.replace("# Lunar Agent 修复后分阶段评测",
                        "# Lunar Agent HTTP deadline评测（Feature 082）", 1)
    from famou.subject_diagnostics import normalize_diagnostic

    lines = ["", "## 终止请求诊断（仅辅助观察）", "",
             "诊断不授予 subject receipt、harness 或分数权限；缺失或无效诊断保持未知。",
             "请求耗时仅描述最终失败请求，不是 Master 精确时长，也不恢复失败请求的完整用量或费用。",
             "本轮测量集成的079/080/081，不能单独归因 HTTP deadline，也不能倒推078失败原因。", "",
             "| Slot | 诊断状态 | stage/code | HTTP | typed reason/status | phase | elapsed ms | timeout ms |",
             "|---:|---|---|---|---|---|---:|---:|"]

    def cell(value):
        return "null" if value is None else str(value)

    for slot in audited.get("slots", []):
        diagnostic = slot.get("terminal_diagnostic", {"status": "unavailable", "payload": None})
        status = diagnostic["status"]
        if status not in {"unavailable", "rejected", "validated"}:
            raise ValueError("invalid diagnostic report status")
        values = [None] * 6
        if status == "validated":
            payload = normalize_diagnostic(diagnostic["payload"])
            model, observation = payload.get("model_failure", {}), payload.get("request_observation", {})
            values = [payload["stage"] + "/" + payload["code"], payload["http_status"],
                      cell(model.get("reason")) + "/" + cell(model.get("response_status")),
                      observation.get("phase"), observation.get("elapsed_ms"), observation.get("request_timeout_ms")]
        if type(slot["index"]) is not int or slot["index"] not in {1, 2}:
            raise ValueError("invalid diagnostic report slot")
        lines.append("| " + " | ".join(map(cell, [slot["index"], status, *values])) + " |")
    return text.rstrip() + "\n" + "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", type=Path, help="saved successful Feature 082 read-only audit")
    args = parser.parse_args()
    print(render_report(json.loads(args.audit.read_bytes())), end="")


if __name__ == "__main__":
    main()
