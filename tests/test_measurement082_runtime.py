"""Offline subject-interpreter identity guards; no credentials or subject execution."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "specs/082-http-deadline-measurement/measurement/runtime_identity.py"
LAUNCHER_BODY = '''# -*- coding: utf-8 -*-
import sys
from famou.cli import main
if __name__ == "__main__":
    if sys.argv[0].endswith("-script.pyw"):
        sys.argv[0] = sys.argv[0][:-11]
    elif sys.argv[0].endswith(".exe"):
        sys.argv[0] = sys.argv[0][:-4]
    sys.exit(main())
'''


@pytest.fixture
def identity():
    spec = importlib.util.spec_from_file_location("offline082_runtime_identity", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fixture_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".venv/bin").mkdir(parents=True)
    (repo / "src/famou").mkdir(parents=True)
    binary = tmp_path / "python-real"
    binary.write_bytes(b"fixture interpreter")
    binary.chmod(0o755)
    interpreter = repo / ".venv/bin/python"
    interpreter.symlink_to(binary)
    launcher = repo / ".venv/bin/lunar-agent"
    launcher.write_text(f"#!{interpreter}\n{LAUNCHER_BODY}")
    launcher.chmod(0o755)
    for name in ("runtime", "http_transport"):
        (repo / f"src/famou/{name}.py").write_text(f"# fixture {name}\n")
    return repo


def probe_result(repo):
    interpreter = repo / ".venv/bin/python"
    return {
        "executable": str(interpreter), "resolved_executable": str(interpreter.resolve()),
        "python_version": "3.11 fixture", "ssl_version": "OpenSSL fixture",
        "modules": {
            name: {
                "path": str(repo / f"src/famou/{name.rsplit('.', 1)[1]}.py"),
                "sha256": hashlib.sha256(
                    (repo / f"src/famou/{name.rsplit('.', 1)[1]}.py").read_bytes()
                ).hexdigest(),
            }
            for name in ("famou.runtime", "famou.http_transport")
        },
        "worker_command": [str(interpreter), "-I", "-S", "-B",
                           str(repo / "src/famou/http_transport.py"), "17"],
    }


def test_capture_uses_console_shebang_not_parent_python(identity, fixture_repo, monkeypatch):
    calls = []
    def probe(interpreter, launcher):
        calls.append((interpreter, launcher))
        return probe_result(fixture_repo)
    monkeypatch.setattr(identity, "_probe", probe)
    value = identity.capture(fixture_repo)
    expected_python = fixture_repo / ".venv/bin/python"
    assert str(expected_python) != sys.executable
    assert calls == [(expected_python, fixture_repo / ".venv/bin/lunar-agent")]
    assert value["schema_version"] == "1"
    assert value["interpreter"]["path"] == str(expected_python)
    assert value["interpreter"]["resolved_path"] == str(expected_python.resolve())
    assert value["interpreter"]["sha256"] == hashlib.sha256(b"fixture interpreter").hexdigest()
    assert identity.verify(fixture_repo, json.loads(json.dumps(value))) == value


@pytest.mark.parametrize("replacement", [
    "#!/usr/bin/env python\n" + LAUNCHER_BODY,
    "#!/tmp/python -I\n" + LAUNCHER_BODY,
    "#!relative/python\n" + LAUNCHER_BODY,
    "#!/tmp/python\nfrom evil import main\nmain()\n",
    "#!/tmp/python\n" + LAUNCHER_BODY + "print('extra')\n",
    "x" * 4097,
])
def test_rejects_unsupported_launcher_before_process(
    identity, fixture_repo, monkeypatch, replacement,
):
    (fixture_repo / ".venv/bin/lunar-agent").write_text(replacement)
    monkeypatch.setattr(identity, "_probe", lambda *_: pytest.fail("must fail before process"))
    with pytest.raises(ValueError, match="subject runtime"):
        identity.capture(fixture_repo)


@pytest.mark.parametrize("drift", ["interpreter", "launcher", "runtime", "helper", "symlink"])
def test_verify_rejects_drift(identity, fixture_repo, monkeypatch, drift):
    monkeypatch.setattr(identity, "_probe", lambda *_: probe_result(fixture_repo))
    expected = identity.capture(fixture_repo)
    paths = {
        "interpreter": fixture_repo / ".venv/bin/python",
        "launcher": fixture_repo / ".venv/bin/lunar-agent",
        "runtime": fixture_repo / "src/famou/runtime.py",
        "helper": fixture_repo / "src/famou/http_transport.py",
    }
    if drift == "symlink":
        target = fixture_repo / ".venv/bin/other-python"
        target.write_bytes(b"fixture interpreter")
        target.chmod(0o755)
        paths["interpreter"].unlink()
        paths["interpreter"].symlink_to(target)
    else:
        path = paths[drift]
        path.write_bytes(path.read_bytes() + b"# drift\n")
    monkeypatch.setattr(identity, "_probe", lambda *_: pytest.fail("drift must fail before process"))
    with pytest.raises(ValueError, match="subject runtime"):
        identity.verify(fixture_repo, expected)


@pytest.mark.parametrize("field", ["executable", "resolved_executable", "runtime_path",
                                   "helper_path", "runtime_sha", "helper_sha", "worker_python",
                                   "worker_flag", "worker_helper", "worker_extra", "extra"])
def test_rejects_wrong_interpreter_import_or_worker_command(
    identity, fixture_repo, monkeypatch, field,
):
    value = probe_result(fixture_repo)
    if field in {"executable", "resolved_executable"}:
        value[field] = "/unexpected/python"
    elif field in {"runtime_path", "helper_path", "runtime_sha", "helper_sha"}:
        name = "famou.runtime" if field.startswith("runtime") else "famou.http_transport"
        key = "path" if field.endswith("path") else "sha256"
        value["modules"][name][key] = "/wrong/module.py" if key == "path" else "0" * 64
    elif field == "worker_python":
        value["worker_command"][0] = "/unexpected/python"
    elif field == "worker_flag":
        value["worker_command"].remove("-S")
    elif field == "worker_helper":
        value["worker_command"][4] = "src/famou/http_transport.py"
    elif field == "worker_extra":
        value["worker_command"].append("extra")
    else:
        value["unexpected"] = "field"
    monkeypatch.setattr(identity, "_probe", lambda *_: value)
    with pytest.raises(ValueError, match="subject runtime"):
        identity.capture(fixture_repo)


@pytest.mark.parametrize("key", ["python_version", "ssl_version"])
def test_verify_rejects_runtime_version_drift(identity, fixture_repo, monkeypatch, key):
    value = probe_result(fixture_repo)
    monkeypatch.setattr(identity, "_probe", lambda *_: value)
    expected = identity.capture(fixture_repo)
    value[key] += " changed"
    with pytest.raises(ValueError, match="subject runtime"):
        identity.verify(fixture_repo, expected)


def test_rejects_mutation_during_probe(identity, fixture_repo, monkeypatch):
    def probe(*_):
        value = probe_result(fixture_repo)
        path = fixture_repo / ".venv/bin/python"
        path.write_bytes(b"changed during probe")
        return value
    monkeypatch.setattr(identity, "_probe", probe)
    with pytest.raises(ValueError, match="subject runtime"):
        identity.capture(fixture_repo)


def test_verify_expected_is_fixed_json(identity, fixture_repo, monkeypatch):
    monkeypatch.setattr(identity, "_probe", lambda *_: probe_result(fixture_repo))
    value = identity.capture(fixture_repo)
    for expected in (None, {}, {**copy.deepcopy(value), "extra": "value"}):
        with pytest.raises(ValueError, match="subject runtime"):
            identity.verify(fixture_repo, expected)


def test_real_local_identity_imports_current_source_without_dispatch(identity, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/untrusted/override")
    monkeypatch.setenv("FAMOU_API_KEY", "fixture-secret-must-not-reach-child")
    value = identity.capture(ROOT)
    assert value["interpreter"]["path"] == str(ROOT / ".venv/bin/python")
    assert value["modules"]["famou.runtime"]["path"] == str(ROOT / "src/famou/runtime.py")
    assert value["worker_command"] == [str(ROOT / ".venv/bin/python"), "-I", "-S", "-B",
                                      str(ROOT / "src/famou/http_transport.py"), "17"]
    assert "fixture-secret" not in json.dumps(value)


def test_probe_matches_console_import_environment(identity, tmp_path, monkeypatch):
    launcher = tmp_path / "lunar-agent"
    monkeypatch.setenv("FAMOU_API_KEY", "fixture-not-inherited")
    monkeypatch.setenv("PYTHONPATH", "/fixture/not-inherited")
    monkeypatch.setattr(identity, "_PROBE", """
import json, os, sys
sys.path[0] = sys.argv[1]
print(json.dumps({'path0': sys.path[0], 'env': dict(os.environ)}))
""")
    value = identity._probe(Path(sys.executable), launcher)
    assert value == {"path0": str(tmp_path), "env": {
        "PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
    }}


@pytest.mark.parametrize("script", [
    "print('{bad json')",
    "print('{\"same\":1,\"same\":2}')",
    "print('[]')",
    "print('{\"value\":NaN}')",
    "print('x' * 40000)",
    "raise RuntimeError('fixture-secret-must-not-be-exposed')",
    "import time; time.sleep(10)",
])
def test_probe_output_and_duration_are_bounded(identity, tmp_path, monkeypatch, script):
    monkeypatch.setattr(identity, "_PROBE", script)
    monkeypatch.setattr(identity, "_PROBE_SECONDS", 0.25)
    with pytest.raises(ValueError, match="^subject runtime probe failed$"):
        identity._probe(Path(sys.executable), tmp_path / "lunar-agent")


def test_probe_timeout_reaps_owned_child(identity, tmp_path, monkeypatch):
    children = []
    popen = identity.subprocess.Popen
    def record_child(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(identity.subprocess, "Popen", record_child)
    monkeypatch.setattr(identity, "_PROBE", "import time; time.sleep(10)")
    monkeypatch.setattr(identity, "_PROBE_SECONDS", 0.2)
    with pytest.raises(ValueError, match="^subject runtime probe failed$"):
        identity._probe(Path(sys.executable), tmp_path / "lunar-agent")
    assert len(children) == 1 and children[0].returncode is not None
    assert children[0].stdout.closed
    with pytest.raises(ChildProcessError):
        os.waitpid(children[0].pid, os.WNOHANG)
