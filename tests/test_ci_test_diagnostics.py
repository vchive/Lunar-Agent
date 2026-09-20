"""Exercise failure visibility without rerunning the regression suites."""
from __future__ import annotations

import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "annotate_test_failures", Path(__file__).resolve().parents[1] / "tools/annotate_test_failures.py",
)
assert _SPEC and _SPEC.loader
diagnostics = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(diagnostics)


def _report(path: Path, cases: list[ET.Element]) -> Path:
    suite = ET.Element("testsuite")
    suite.extend(cases)
    ET.ElementTree(suite).write(path)
    return path


def _case(name: str, *, kind: str = "failure", message: str = "assert 1 == 2") -> ET.Element:
    case = ET.Element("testcase", classname="tests.test_example.TestWorker", name=name)
    ET.SubElement(case, kind, message=message)
    return case


def test_failure_node_ids_and_escaped_reasons_are_visible(tmp_path, capsys):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_example.py").touch()
    report = _report(tmp_path / "current.xml", [
        _case("test_cancel[param]", message="bad 100%\r\n::warning::injected"),
        _case("test_start", kind="error", message="setup failed"),
    ])

    assert diagnostics.annotate([report], repo=tmp_path) == 1
    output = capsys.readouterr().out
    assert "file=tests/test_example.py" in output
    assert "tests/test_example.py::TestWorker::test_cancel[param]" in output
    assert "bad 100%25%0D%0A::warning::injected" in output
    assert "tests/test_example.py::TestWorker::test_start%0Asetup failed" in output
    assert len([line for line in output.splitlines() if line.startswith("::")]) == 2


def test_unavailable_report_does_not_hide_other_failures(tmp_path, capsys):
    invalid = tmp_path / "invalid.xml"
    invalid.write_text("<testsuite>")
    failed = _report(tmp_path / "frozen123.xml", [_case("test_frozen")])

    assert diagnostics.annotate([tmp_path / "missing.xml", invalid, failed]) == 1
    output = capsys.readouterr().out
    assert "missing.xml: JUnit report unavailable" in output
    assert "invalid.xml: JUnit report unavailable" in output
    assert "frozen123.xml: tests.test_example.TestWorker::test_frozen" in output
    assert "1 failures/errors; 2 unavailable reports" in output


def test_annotations_are_bounded_across_reports(tmp_path, capsys):
    reports = [_report(tmp_path / f"{index}.xml", [
        _case(f"test_{index}_{case}", message="x" * 5000) for case in range(6)
    ]) for index in range(2)]

    assert diagnostics.annotate(reports) == 1
    output = capsys.readouterr().out
    assert output.count("::error ") == 10
    assert "2 additional failures are in the test artifacts" in output
    assert "x" * 2001 not in output


def test_pass_and_skip_reports_succeed_without_errors(tmp_path, capsys):
    passing = ET.Element("testcase", classname="tests.test_example", name="test_pass")
    skipped = ET.Element("testcase", classname="tests.test_example", name="test_skip")
    ET.SubElement(skipped, "skipped")
    reports = [_report(tmp_path / "current.xml", [passing, skipped]),
               _report(tmp_path / "frozen123.xml", [passing])]

    assert diagnostics.annotate(reports) == 0
    assert "::error" not in capsys.readouterr().out
