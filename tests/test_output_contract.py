import json
from pathlib import Path

import pytest

from famou import evaluator
from famou.algorithm import OutputSpec


def test_output_contract_validates_all_32_declarations_and_last_failure(tmp_path: Path) -> None:
    outputs = tuple(OutputSpec(f"output/{i}.json", "json", ("answer",)) for i in range(32))
    (tmp_path / "output").mkdir()
    for spec in outputs:
        (tmp_path / spec.path).write_text('{"answer": "PRIVATE_DATA_MARKER"}')
    passed = evaluator.evaluate_output_contract(outputs, tmp_path)
    assert passed.passed
    assert len(passed.details["checks"]) == 32
    assert "PRIVATE_DATA_MARKER" not in json.dumps(passed.as_dict())
    (tmp_path / outputs[-1].path).write_text('{"wrong": "PRIVATE_DATA_MARKER"}')
    failed = evaluator.evaluate_output_contract(outputs, tmp_path)
    assert not failed.passed
    assert failed.details["checks"][-1]["passed"] is False
    assert "PRIVATE_DATA_MARKER" not in json.dumps(failed.as_dict())


@pytest.mark.parametrize("specs", [
    "output/file.json", {"path": "output/file.json"}, [object()],
    [OutputSpec("output/file.json", "json")] * 33,
    [OutputSpec("output/file.json", "json")] * 2,
])
def test_output_contract_rejects_invalid_declarations(tmp_path: Path, specs: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        evaluator.evaluate_output_contract(specs, tmp_path)


@pytest.mark.parametrize("state", ["absent", "valid", "invalid", "directory", "dangling", "loop"])
def test_optional_output_is_checked_unless_truly_absent(tmp_path: Path, state: str) -> None:
    target = tmp_path / "output/summary.json"
    target.parent.mkdir()
    if state == "valid":
        target.write_text('{"answer": 42}')
    elif state == "invalid":
        target.write_text('{"wrong": 42}')
    elif state == "directory":
        target.mkdir()
    elif state == "dangling":
        target.symlink_to("missing.json")
    elif state == "loop":
        target.symlink_to(target.name)
    result = evaluator.evaluate_output_contract(
        (OutputSpec("output/summary.json", "json", ("answer",), required=False),), tmp_path,
    )
    assert result.passed is (state in {"absent", "valid"})
    assert len(result.details["checks"]) == (0 if state == "absent" else 1)


def test_output_contract_allows_no_declared_outputs(tmp_path: Path) -> None:
    assert evaluator.evaluate_output_contract((), tmp_path).passed
