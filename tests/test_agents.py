import sys
from pathlib import Path

import pytest

from famou.agents import (
    AgentInvocationError,
    AgentRegistry,
    AgentRequest,
    AgentResult,
    AgentSelectionError,
    CommandAgentAdapter,
    RuntimeAgentAdapter,
)
from famou.runtime import MockRuntime


class FixtureAdapter:
    def __init__(self, name: str, roles=("solver",), capabilities=()):
        self.name = name
        self.roles = frozenset(roles)
        self.capabilities = frozenset(capabilities)

    def run(self, request):
        return AgentResult(self.name, request.role, "done")

    def cancel(self):
        return None

    def process_info(self):
        return (None, None)

    def set_process_observer(self, observer):
        del observer


def request(tmp_path: Path) -> AgentRequest:
    return AgentRequest("run-1", "task-1", "solver", "solve this", workspace=tmp_path)


def command_adapter(code: str, tmp_path: Path, **kwargs) -> CommandAgentAdapter:
    return CommandAgentAdapter([sys.executable, "-c", code], **kwargs)


def test_registry_is_deterministic_and_rejects_duplicates(tmp_path: Path) -> None:
    first = FixtureAdapter("zeta", capabilities=("read_files",))
    second = FixtureAdapter("alpha", capabilities=("read_files",))
    registry = AgentRegistry([first, second])
    assert registry.select("solver", ("read_files",)).name == "alpha"
    assert registry.select("solver", ("read_files",)).name == "alpha"
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(FixtureAdapter("alpha"))


def test_registry_preferred_adapter_must_be_compatible() -> None:
    registry = AgentRegistry([FixtureAdapter("worker", capabilities=("read_files",))])
    with pytest.raises(AgentSelectionError, match="missing capabilities"):
        registry.select("solver", ("write_artifacts",), preferred="worker")
    with pytest.raises(AgentSelectionError, match="no registered"):
        registry.select("solver", ("write_artifacts",))


def test_request_and_result_validate_bounds_and_paths(tmp_path: Path) -> None:
    req = request(tmp_path)
    assert req.to_dict()["workspace"] == str(tmp_path.resolve())
    assert AgentResult("worker", "solver", "ok", ("nested/out.txt",)).artifacts == (
        "nested/out.txt",
    )
    with pytest.raises(ValueError, match="run-relative"):
        AgentResult("worker", "solver", "ok", ("../escape.txt",))
    with pytest.raises(ValueError, match="absolute"):
        AgentRequest("r", "t", "solver", "x", workspace=Path("relative"))


def test_command_adapter_normalizes_json_and_plain_text(tmp_path: Path) -> None:
    code = (
        "import json,sys,pathlib; r=json.loads(sys.stdin.read()); "
        "pathlib.Path(r['workspace'],'answer.txt').write_text('answer'); "
        "print(json.dumps({'status':'succeeded','text':'ok','artifacts':['answer.txt'],"
        "'metadata':{'provider':'fixture'}}))"
    )
    adapter = command_adapter(code, tmp_path, name="fixture", roles=("solver",))
    result = adapter.run(request(tmp_path))
    assert result.adapter_name == "fixture"
    assert result.artifacts == ("answer.txt",)
    assert (tmp_path / "answer.txt").read_text() == "answer"

    plain = command_adapter("import sys; print('plain result')", tmp_path, name="plain")
    assert plain.run(request(tmp_path)).text == "plain result"


def test_command_adapter_rejects_malformed_nonzero_and_timeout(tmp_path: Path) -> None:
    malformed = command_adapter("print('{')", tmp_path)
    with pytest.raises(AgentInvocationError, match="malformed JSON"):
        malformed.run(request(tmp_path))

    failing = command_adapter("import sys; print('bad', file=sys.stderr); sys.exit(3)", tmp_path)
    with pytest.raises(AgentInvocationError, match="exited with code 3"):
        failing.run(request(tmp_path))

    slow = command_adapter("import time; time.sleep(2)", tmp_path)
    short = AgentRequest("r", "t", "solver", "x", workspace=tmp_path, timeout=0.05)
    with pytest.raises(AgentInvocationError, match="timed out"):
        slow.run(short)


def test_command_adapter_requires_absolute_executable() -> None:
    with pytest.raises(ValueError, match="absolute"):
        CommandAgentAdapter(["python", "-c", "print('x')"])


def test_runtime_adapter_preserves_existing_runtime_contract(tmp_path: Path) -> None:
    adapter = RuntimeAgentAdapter(MockRuntime(), name="hermes-compatible")
    result = adapter.run(request(tmp_path))
    assert result.adapter_name == "hermes-compatible"
    assert result.role == "solver"
    assert "Mock runtime" in result.text
