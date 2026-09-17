"""The split runner executes historical registration tests against their actual product."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("regression_runner", REPO / "tools/run_tests.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


@pytest.fixture(scope="module")
def frozen():
    with runner._frozen_snapshot(REPO) as snapshot:
        yield snapshot


def test_frozen_snapshot_verifies_every_registered_file_and_original_product_tree(frozen, monkeypatch):
    observed = set()
    read_bytes = Path.read_bytes

    def record(path):
        observed.add(path.relative_to(frozen).as_posix())
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", record)
    manifest = runner._verify_frozen(frozen)
    assert {group: len(manifest[group]) for group in runner.PIN_COUNTS} == {
        "product_files": 77, "measurement_files": 14, "historical_files": 69,
    }
    expected = {name for group in runner.PIN_COUNTS for name in manifest[group]}
    assert observed == expected | {runner.MANIFEST_PATH}
    assert runner._git(frozen, "rev-parse", "HEAD") == runner.FROZEN_COMMIT
    assert runner._git(
        frozen, "diff", "--name-only", runner.PRODUCT_COMMIT, "HEAD", "--", "src", "pyproject.toml",
    ) == ""


@pytest.mark.parametrize("group", ["product_files", "measurement_files", "historical_files"])
def test_registered_byte_drift_is_rejected_without_editing_historical_files(frozen, monkeypatch, group):
    manifest = runner._verify_frozen(frozen)
    changed = frozen / next(iter(manifest[group]))
    read_bytes = Path.read_bytes

    def drift(path):
        content = read_bytes(path)
        return content + b"changed" if path == changed else content

    monkeypatch.setattr(Path, "read_bytes", drift)
    with pytest.raises(runner.RegressionError, match="registered file changed"):
        runner._verify_frozen(frozen)


def test_manifest_identity_is_checked_before_its_file_pins(frozen, monkeypatch):
    read_bytes = Path.read_bytes

    def drift(path):
        content = read_bytes(path)
        return content + b"\n" if path == frozen / runner.MANIFEST_PATH else content

    monkeypatch.setattr(Path, "read_bytes", drift)
    with pytest.raises(runner.RegressionError, match="immutable Feature 123 manifest changed"):
        runner._verify_frozen(frozen)


def test_frozen_imports_override_inherited_current_checkout_and_pytest_filters(frozen, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(REPO / "src"))
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k nonexistent")
    monkeypatch.setenv("PYTEST_PLUGINS", "unwanted_plugin")
    environment = runner._environment(frozen)
    assert environment["PYTHONPATH"] == str(frozen / "src")
    assert environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert "PYTEST_ADDOPTS" not in environment and "PYTEST_PLUGINS" not in environment
    assert [Path(path).resolve() for path in runner._verify_imports(frozen)] == [
        (frozen / "src/famou/__init__.py").resolve(),
        (frozen / "src/famou/evaluator_bundle.py").resolve(),
    ]


def test_fixed_nodes_are_exactly_original_tests_requiring_registration_fixture(frozen):
    source = (frozen / runner.REGISTRATION_TEST).read_text()
    parsed = ast.parse(source)
    registered_functions = {
        item.name for item in parsed.body if isinstance(item, ast.FunctionDef)
        and item.name.startswith("test_") and any(argument.arg == "registered" for argument in item.args.args)
    }
    all_nodes = runner._collect(frozen, (runner.REGISTRATION_TEST,))
    expected = {node for node in all_nodes if node.split("::", 1)[1].split("[", 1)[0] in registered_functions}
    assert len(expected) == 24
    assert set(runner.BOUND_NODES) == expected
    assert set(runner._collect(frozen, runner.BOUND_NODES)) == expected
    assert runner._current_selection(all_nodes) == len(all_nodes) - 24


@pytest.mark.parametrize("mutation", ["omission", "prefix_collision", "extra_bound_node"])
def test_current_deselection_cannot_silently_drop_or_omit_tests(monkeypatch, mutation):
    nodes = (*runner.BOUND_NODES, "tests/test_current.py::test_current")
    if mutation == "omission":
        nodes = nodes[1:]
    elif mutation == "prefix_collision":
        nodes = (*nodes, runner.BOUND_NODES[0] + "_additional")
    else:
        monkeypatch.setattr(runner, "BOUND_NODES", (*runner.BOUND_NODES, nodes[-1]))
    with pytest.raises(runner.RegressionError, match="24"):
        runner._current_selection(nodes)


def test_detached_worktree_is_removed_when_body_raises():
    before = runner._git(REPO, "worktree", "list", "--porcelain")
    with pytest.raises(runner.RegressionError, match="fixture failure"), runner._frozen_snapshot(REPO) as snapshot:
        assert snapshot.is_dir()
        raise runner.RegressionError("fixture failure")
    assert not snapshot.exists()
    assert runner._git(REPO, "worktree", "list", "--porcelain") == before


@pytest.mark.parametrize("current_exit,frozen_exit", [(1, 0), (0, 3), (0, 0)])
def test_both_phase_results_propagate_and_cleanup_after_pytest_failure(
    tmp_path, monkeypatch, current_exit, frozen_exit,
):
    phases = []

    def collect(root, selections):
        return (*runner.BOUND_NODES, "tests/test_current.py::test_current") if root == REPO else runner.BOUND_NODES

    def phase(root, selections, report, *, expected_count, frozen=False):
        phases.append((root, selections, report, expected_count, frozen))
        return {"exit_code": frozen_exit if frozen else current_exit}

    monkeypatch.setattr(runner, "_collect", collect)
    monkeypatch.setattr(runner, "_pytest_phase", phase)
    before = runner._git(REPO, "worktree", "list", "--porcelain")
    assert runner.run(REPO, tmp_path / "junit") == (current_exit or frozen_exit)
    current, frozen = phases
    assert current == (
        REPO, ("tests", *(f"--deselect={node}" for node in runner.BOUND_NODES)),
        (tmp_path / "junit/current.xml").resolve(), 1, False,
    )
    assert frozen[1:] == (runner.BOUND_NODES, (tmp_path / "junit/frozen123.xml").resolve(), 24, True)
    assert not frozen[0].exists()
    assert runner._git(REPO, "worktree", "list", "--porcelain") == before


@pytest.mark.parametrize("content,count,expected", [
    ("def test_one():\n    assert True\n", 1, 0),
    ("def test_one():\n    assert False\n", 1, 1),
    ("import pytest\ndef test_one():\n    pytest.skip('fixture')\n", 1, 1),
    ("def test_one():\n    assert True\n", 2, 1),
])
def test_real_pytest_phase_requires_expected_count_and_no_frozen_skips(tmp_path, content, count, expected):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_fixture.py").write_text(content)
    report = tmp_path / "result.xml"
    result = runner._pytest_phase(tmp_path, ("tests",), report, expected_count=count, frozen=True)
    assert result["exit_code"] == expected
    assert result["tests"] == 1
    assert report.is_file()
