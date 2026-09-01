import sys
from pathlib import Path

import pytest

from famou.artifacts import ArtifactError, ArtifactStore
from famou.runtime import MockRuntime, RuntimeExecutionError, SubprocessRuntime
from famou.store import Store


def test_mock_runtime_is_deterministic_without_external_environment(tmp_path: Path) -> None:
    result = MockRuntime().run("  hello   local agent ", tmp_path)
    assert result.text == "Mock runtime completed the task: hello local agent"
    assert result.metadata["provider"] == "repository-mock"


def test_subprocess_runtime_uses_explicit_command_and_workspace(tmp_path: Path) -> None:
    command = [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"]
    result = SubprocessRuntime(command).run("hello", tmp_path)
    assert result.text == "HELLO"


def test_subprocess_runtime_requires_explicit_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FAMOU_RUNTIME_COMMAND", raising=False)
    with pytest.raises(ValueError, match="requires FAMOU_RUNTIME_COMMAND"):
        SubprocessRuntime()


def test_subprocess_runtime_reports_nonzero_exit(tmp_path: Path) -> None:
    command = [sys.executable, "-c", "import sys; print('bad', file=sys.stderr); sys.exit(3)"]
    with pytest.raises(RuntimeExecutionError, match="code 3"):
        SubprocessRuntime(command).run("hello", tmp_path)


def test_subprocess_runtime_enforces_timeout(tmp_path: Path) -> None:
    command = [sys.executable, "-c", "import time; time.sleep(1)"]
    with pytest.raises(RuntimeExecutionError, match="timed out"):
        SubprocessRuntime(command).run("hello", tmp_path, timeout=0.01)


def test_artifact_paths_are_confined_to_run_workspace(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("goal", tmp_path / "workspace")
    artifacts = ArtifactStore(run.workspace, store, run.id)
    with pytest.raises(ArtifactError):
        artifacts.safe_path("../outside.txt")
