"""Run current regressions and the 24 immutable Feature 123 registration tests separately.

The historical tests intentionally require the product used by their preregistration. They
run unchanged in a local detached worktree; this script never fetches or invokes a campaign.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[1]
FROZEN_COMMIT = "5560eb9f67463badc31fed17e309bb5dc1dabf8f"
PRODUCT_COMMIT = "519fea5ca70ac1ede3df356ee7391112801ab45d"
MANIFEST_PATH = "specs/123-small-evaluator-diagnostic/measurement/manifest.json"
MANIFEST_SHA256 = "9d05c7d95eb427f60d7be7a93dbfb8c7c53ec50904169e0391053292315f60a7"
PIN_COUNTS = {"product_files": 77, "measurement_files": 14, "historical_files": 69}
REGISTRATION_TEST = "tests/test_measurement123_registration.py"
BOUND_NODES = (
    REGISTRATION_TEST + "::test_offline_registration_is_once_only_and_verifies_without_provider_requests",
    REGISTRATION_TEST + "::test_changed_fixed_conditions_are_rejected[limits]",
    REGISTRATION_TEST + "::test_changed_fixed_conditions_are_rejected[contract]",
    REGISTRATION_TEST + "::test_changed_fixed_conditions_are_rejected[contract_sha256]",
    REGISTRATION_TEST + "::test_changed_fixed_conditions_are_rejected[input_utf8]",
    REGISTRATION_TEST + "::test_changed_fixed_conditions_are_rejected[input_sha256]",
    REGISTRATION_TEST + "::test_changed_fixed_conditions_are_rejected[input_profile]",
    REGISTRATION_TEST + "::test_changed_fixed_conditions_are_rejected[holdouts]",
    REGISTRATION_TEST + "::test_changed_fixed_conditions_are_rejected[planned_attempts]",
    REGISTRATION_TEST + "::test_changed_fixed_conditions_are_rejected[retries_or_replacements]",
    REGISTRATION_TEST + "::test_changed_fixed_conditions_are_rejected[sampling]",
    REGISTRATION_TEST + "::test_changed_fixed_conditions_are_rejected[runtime_options]",
    REGISTRATION_TEST + "::test_changed_fixed_conditions_are_rejected[compiler_request]",
    REGISTRATION_TEST + "::test_changed_fixed_conditions_are_rejected[provider]",
    REGISTRATION_TEST + "::test_changed_fixed_conditions_are_rejected[campaign_root]",
    REGISTRATION_TEST + "::test_changed_fixed_conditions_are_rejected[primary]",
    REGISTRATION_TEST + "::test_changed_fixed_conditions_are_rejected[secondary]",
    REGISTRATION_TEST + "::test_changed_fixed_conditions_are_rejected[joint]",
    REGISTRATION_TEST + "::test_registered_byte_drift_is_rejected[product_files]",
    REGISTRATION_TEST + "::test_registered_byte_drift_is_rejected[measurement_files]",
    REGISTRATION_TEST + "::test_registered_byte_drift_is_rejected[historical_files]",
    REGISTRATION_TEST + "::test_file_set_omission_is_rejected[product_files]",
    REGISTRATION_TEST + "::test_file_set_omission_is_rejected[measurement_files]",
    REGISTRATION_TEST + "::test_file_set_omission_is_rejected[historical_files]",
)


class RegressionError(RuntimeError):
    pass


def _capture(command, root, *, environment=None):
    result = subprocess.run(
        command, cwd=root, env=environment, text=True, capture_output=True, check=False,
    )
    if result.returncode:
        raise RegressionError(f"command failed ({result.returncode}): {' '.join(command[:3])}\n"
                              + result.stdout + result.stderr)
    return result.stdout.strip()


def _git(root, *arguments):
    return _capture(["git", *arguments], root)


def _environment(root):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment.pop("PYTEST_ADDOPTS", None)
    environment.pop("PYTEST_PLUGINS", None)
    return environment


@contextmanager
def _frozen_snapshot(repo):
    with tempfile.TemporaryDirectory(prefix="lunar-regression-") as directory:
        snapshot = Path(directory) / "frozen123"
        added = False
        try:
            _git(repo, "worktree", "add", "--detach", str(snapshot), FROZEN_COMMIT)
            added = True
            yield snapshot
        finally:
            if added or snapshot.exists():
                _git(repo, "worktree", "remove", "--force", str(snapshot))


def _verify_frozen(snapshot):
    if _git(snapshot, "rev-parse", "HEAD") != FROZEN_COMMIT:
        raise RegressionError("frozen worktree is not the fixed Feature 123 commit")
    _git(snapshot, "diff", "--exit-code", PRODUCT_COMMIT, FROZEN_COMMIT, "--", "src", "pyproject.toml")
    raw = (snapshot / MANIFEST_PATH).read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise RegressionError("immutable Feature 123 manifest changed")
    manifest = json.loads(raw)
    if manifest["product_commit"] != PRODUCT_COMMIT:
        raise RegressionError("registered product commit changed")
    for group, count in PIN_COUNTS.items():
        pins = manifest[group]
        if len(pins) != count:
            raise RegressionError(f"registered {group} count changed")
        for name, digest in pins.items():
            relative = PurePosixPath(name)
            path = snapshot / relative
            if (relative.is_absolute() or ".." in relative.parts or path.is_symlink()
                    or not path.resolve().is_relative_to(snapshot.resolve())
                    or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
                raise RegressionError(f"registered file changed: {name}")
    tracked = set(_git(snapshot, "ls-files", "src", "pyproject.toml").splitlines())
    sources = {path.relative_to(snapshot).as_posix() for path in (snapshot / "src").rglob("*.py")}
    if (tracked != set(manifest["product_files"])
            or sources != {name for name in tracked if name.startswith("src/") and name.endswith(".py")}):
        raise RegressionError("registered product file set changed")
    return manifest


def _verify_imports(root):
    code = (
        "import json, famou, famou.evaluator_bundle; "
        "print(json.dumps([famou.__file__, famou.evaluator_bundle.__file__]))"
    )
    origins = json.loads(_capture([sys.executable, "-c", code], root, environment=_environment(root)))
    expected = [root / "src/famou/__init__.py", root / "src/famou/evaluator_bundle.py"]
    if [Path(path).resolve() for path in origins] != [path.resolve() for path in expected]:
        raise RegressionError("Python imported famou from a different checkout")
    return origins


def _collect(root, selections):
    output = _capture(
        [sys.executable, "-m", "pytest", "-o", "addopts=", "--collect-only", "-q", "--color=no", *selections],
        root, environment=_environment(root),
    )
    nodes = tuple(line for line in output.splitlines() if line.startswith("tests/") and "::" in line)
    if not nodes or len(set(nodes)) != len(nodes):
        raise RegressionError("pytest collection was empty or contained duplicate node IDs")
    return nodes


def _current_selection(nodes):
    if len(BOUND_NODES) != 24 or len(set(BOUND_NODES)) != 24:
        raise RegressionError("the fixed registration selection must contain exactly 24 nodes")
    removed = tuple(node for node in nodes if node.startswith(BOUND_NODES))
    if len(removed) != 24 or set(removed) != set(BOUND_NODES):
        raise RegressionError("current collection must deselect exactly the 24 original registration nodes")
    return len(nodes) - len(removed)


def _pytest_phase(root, selections, report, *, expected_count, frozen=False):
    if report.exists():
        report.unlink()
    command = [sys.executable, "-m", "pytest", "-o", "addopts=", "-q", "--color=no",
               f"--junitxml={report}", *selections]
    result = subprocess.run(command, cwd=root, env=_environment(root), check=False)
    summary = {"exit_code": result.returncode, "junit": str(report)}
    try:
        suites = list(ET.parse(report).getroot().iter("testsuite"))
        summary.update({field: sum(int(suite.attrib.get(field, "0")) for suite in suites)
                        for field in ("tests", "failures", "errors", "skipped")})
        complete = summary["tests"] == expected_count and not summary["failures"] and not summary["errors"]
        if frozen:
            complete = complete and summary["skipped"] == 0
        if not complete:
            summary["exit_code"] = result.returncode or 1
            summary["validation_error"] = "JUnit did not confirm the expected executed test set"
    except (OSError, ValueError, ET.ParseError):
        summary["exit_code"] = result.returncode or 1
        summary["validation_error"] = "pytest did not produce a readable JUnit report"
    print(json.dumps(summary, sort_keys=True), flush=True)
    return summary


def run(repo, junit_dir):
    repo, junit_dir = repo.resolve(), junit_dir.resolve()
    junit_dir.mkdir(parents=True, exist_ok=True)
    with _frozen_snapshot(repo) as snapshot:
        manifest = _verify_frozen(snapshot)
        if hashlib.sha256((repo / REGISTRATION_TEST).read_bytes()).hexdigest() != manifest["measurement_files"][REGISTRATION_TEST]:
            raise RegressionError("current Feature 123 registration tests differ from the immutable original")
        current_origins, frozen_origins = _verify_imports(repo), _verify_imports(snapshot)
        current_count = _current_selection(_collect(repo, ("tests",)))
        frozen_nodes = _collect(snapshot, BOUND_NODES)
        if len(frozen_nodes) != 24 or set(frozen_nodes) != set(BOUND_NODES):
            raise RegressionError("frozen collection did not select exactly the 24 original registration nodes")
        current_version = {"commit": _git(repo, "rev-parse", "HEAD"), "working_tree": True,
                           "imports": current_origins}
        frozen_version = {"commit": FROZEN_COMMIT, "product_commit": PRODUCT_COMMIT,
                          "pins": PIN_COUNTS, "imports": frozen_origins}
        print(json.dumps({"current": current_version, "frozen123": frozen_version}, sort_keys=True), flush=True)
        current = _pytest_phase(
            repo, ("tests", *(f"--deselect={node}" for node in BOUND_NODES)),
            junit_dir / "current.xml", expected_count=current_count,
        )
        frozen = _pytest_phase(
            snapshot, BOUND_NODES, junit_dir / "frozen123.xml", expected_count=24, frozen=True,
        )
        result = {"current": {**current_version, **current}, "frozen123": {**frozen_version, **frozen},
                  "exit_code": current["exit_code"] or frozen["exit_code"]}
    print(json.dumps(result, sort_keys=True), flush=True)
    return result["exit_code"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        return run(REPO, arguments.junit_dir)
    except (RegressionError, OSError) as exc:
        print(f"regression runner failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
