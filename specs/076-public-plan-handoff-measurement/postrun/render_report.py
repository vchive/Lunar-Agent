"""Render only the current public-plan handoff audit, preserving native scores and nulls."""
import argparse
import json
from pathlib import Path
from types import ModuleType


def _load_adapter():
    path = Path(__file__).resolve().parent.parent / "measurement/adapter.py"
    module = ModuleType("report076_adapter")
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)  # noqa: S102
    return module


_adapter = _load_adapter()


def render_report(audited):
    if (audited.get("kind") != "feature076_postrun_audit"
            or audited.get("implementation_commit") != _adapter.IMPLEMENTATION):
        raise ValueError("wrong public-plan handoff audit identity")
    prior = _adapter.load_previous_postrun("render_report")
    text = prior.render_report(audited)
    return text.replace("# Lunar Agent 修复后分阶段评测",
                        "# Lunar Agent 公共计划交接评测（Feature 076）", 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", type=Path, help="saved successful Feature 076 read-only audit")
    args = parser.parse_args()
    print(render_report(json.loads(args.audit.read_bytes())), end="")


if __name__ == "__main__":
    main()
