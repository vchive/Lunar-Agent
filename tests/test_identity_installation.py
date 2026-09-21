"""Install the new namespace from a wheel and exercise it outside the source checkout."""
from __future__ import annotations

import configparser
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import zipfile
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def installation():
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    uv = shutil.which("uv")
    assert uv is not None, "the regression environment requires uv for isolated installation"
    environment = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR") if key in os.environ}
    environment.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"})
    with tempfile.TemporaryDirectory(prefix="lunar-evolution-install-") as directory:
        temporary = Path(directory).resolve()
        assert not temporary.is_relative_to(root)
        wheels = temporary / "wheels"
        outside = temporary / "outside"
        outside.mkdir()

        def command(argv, *, env=None, cwd=outside):
            result = subprocess.run(
                [str(value) for value in argv], cwd=cwd,
                env=environment if env is None else env,
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=90, check=False,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            return result.stdout

        command([uv, "build", "--offline", "--wheel", "--python", sys.executable,
                 "--out-dir", wheels, root])
        wheel, = wheels.glob("*.whl")
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            roots = {name.split("/", 1)[0] for name in names}
            metadata_root = f"lunar_evolution-{version}.dist-info"
            assert roots == {"lunar_evolution", metadata_root}
            parser = configparser.ConfigParser()
            parser.read_string(archive.read(f"{metadata_root}/entry_points.txt").decode())
            assert dict(parser["console_scripts"]) == {"lunar-evolution": "lunar_evolution.cli:main"}
        virtualenv = temporary / "environment"
        command([uv, "venv", "--offline", "--python", sys.executable, virtualenv])
        python = virtualenv / "bin/python"
        cli = virtualenv / "bin/lunar-evolution"
        command([uv, "pip", "install", "--offline", "--no-deps", "--python", python, wheel])
        yield {
            "command": command, "python": python, "cli": cli, "outside": outside,
            "environment": environment, "virtualenv": virtualenv,
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        }


def test_wheel_has_only_the_new_installed_package_and_entrypoint(installation):
    value = installation
    observed = json.loads(value["command"]([value["python"], "-I", "-c", (
        "import importlib.metadata as m, json, lunar_evolution; "
        "d=m.distribution('lunar-evolution'); "
        "print(json.dumps({'name':d.metadata['Name'],'module':lunar_evolution.__file__,"
        "'entrypoints':{e.name:e.value for e in d.entry_points if e.group=='console_scripts'}}))"
    )]))
    assert observed["name"] == "lunar-evolution"
    assert Path(observed["module"]).is_relative_to(value["virtualenv"])
    assert observed["entrypoints"] == {"lunar-evolution": "lunar_evolution.cli:main"}
    for argv in ([value["cli"], "--help"], [value["python"], "-I", "-m", "lunar_evolution", "--help"]):
        help_text = value["command"](argv)
        assert help_text.startswith("usage: lunar-evolution ")
        assert "Lunar Evolution" in help_text


def test_new_configuration_environment_and_explicit_home_precedence(installation):
    value = installation
    environment = {
        **value["environment"], "LUNAR_EVOLUTION_HOME": str(value["outside"] / "environment-home"),
        "LUNAR_EVOLUTION_MAX_RETRIES": "3", "LUNAR_EVOLUTION_RUNTIME_TIMEOUT": "17",
        "LUNAR_EVOLUTION_MODEL_ENDPOINT": "http://127.0.0.1:1/v1/chat/completions",
        "LUNAR_EVOLUTION_MODEL": "offline-fixture-model",
        "LUNAR_EVOLUTION_API_KEY": "offline-fixture-key",
        "LUNAR_EVOLUTION_RUNTIME_COMMAND": str(value["python"]),
    }
    observed = json.loads(value["command"]([value["python"], "-I", "-c", (
        "import json; from lunar_evolution.config import Config; "
        "from lunar_evolution.runtime import OpenAICompatibleRuntime, SubprocessRuntime; "
        "c=Config.from_env(); r=OpenAICompatibleRuntime(); s=SubprocessRuntime(); "
        "print(json.dumps({'home':str(c.home),'explicit':str(Config.from_env('explicit-home').home),"
        "'retries':c.max_retries,'timeout':c.runtime_timeout,'endpoint':r.endpoint,"
        "'model':r.model,'key_matches':r.api_key=='offline-fixture-key','command':s.command}))"
    )], env=environment))
    assert observed["home"] == str(value["outside"] / "environment-home")
    assert observed["explicit"] == str(value["outside"] / "explicit-home")
    assert observed["retries"] == 3 and observed["timeout"] == 17.0
    assert observed["endpoint"] == "http://127.0.0.1:1/v1/chat/completions"
    assert observed["model"] == "offline-fixture-model"
    assert observed["key_matches"] is True
    assert observed["command"] == [str(value["python"])]
    assert not (value["outside"] / "environment-home").exists()
    assert not (value["outside"] / "explicit-home").exists()


def test_installed_case_digest_uses_the_new_identity_domain(installation):
    value = installation
    case = value["outside"] / "digest-case"
    case.mkdir()
    instruction = case / "instruction.md"
    instruction.write_bytes(b"Task\n")
    instruction.chmod(0o644)
    digest = value["command"]([value["python"], "-I", "-c", (
        "import sys; from lunar_evolution import benchmark_case_content_digest; "
        "print(benchmark_case_content_digest(sys.argv[1]))"
    ), case]).strip()
    assert digest == "sha256:fc5d580c19298f7740cf57d0cce5743389a8e8cb26ff03b5ba32f0af920aa8c0"


def test_installed_mock_run_default_home_status_and_events(installation):
    value = installation
    result = json.loads(value["command"]([
        value["cli"], "run", "create a local report", "--runtime", "mock", "--json",
    ]))
    assert result["status"] == "succeeded"
    home = value["outside"] / ".lunar-evolution"
    assert (home / "state.db").is_file()
    assert Path(result["workspace"]).is_relative_to(home)
    status = json.loads(value["command"]([
        value["python"], "-I", "-m", "lunar_evolution", "status", result["run_id"], "--json",
    ]))
    assert status["status"] == "succeeded"
    events = json.loads(value["command"]([value["cli"], "events", result["run_id"], "--json"]))
    assert events


def test_installed_mock_detached_process_reaches_terminal_state(installation):
    value = installation
    home = value["outside"] / "detached-home"
    environment = {**value["environment"], "LUNAR_EVOLUTION_HOME": str(home)}
    result = json.loads(value["command"]([
        value["cli"], "run", "complete a detached local report", "--runtime", "mock", "--detach", "--json",
    ], env=environment))
    assert result["status"] == "pending"
    deadline = time.monotonic() + 15
    while True:
        status = json.loads(value["command"]([
            value["cli"], "status", result["run_id"], "--home", home, "--json",
        ]))
        if status["status"] in {"succeeded", "failed", "cancelled"}:
            break
        assert time.monotonic() < deadline, status
        time.sleep(0.05)
    log_path = Path(result["workspace"]) / "controller.log"
    assert status["status"] == "succeeded", log_path.read_text()
    assert log_path.is_file()
    assert Path(result["workspace"]).is_relative_to(home)
