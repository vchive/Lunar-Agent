from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from famou.candidate_bundle import parse_candidate_source_bundle
from famou.candidate_workspace import (
    CandidateWorkspaceError,
    build_candidate_workspace_plan,
    candidate_file_table_sha256,
    materialize_candidate_source_bundle,
    parse_candidate_workspace_plan,
    validate_candidate_workspace_plan,
)

CONTRACT = "a" * 64


def _item(path: str, content: bytes) -> dict[str, object]:
    return {"path": path, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def _bundle(tmp_path: Path):
    files = {"main.py": b"raise RuntimeError('marker')\n", "lib/helper.py": b"VALUE = 42\n"}
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return {
        "schema_version": "1", "protocol": "lunar-candidate-source-bundle-v1",
        "contract_sha256": CONTRACT, "entrypoint": "main.py",
        "files": [_item(name, content) for name, content in files.items()],
    }


def test_materialize_copies_only_declared_bytes_and_has_path_free_identity(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    bundle = parse_candidate_source_bundle(_bundle(source))
    root = tmp_path / "workspaces"
    root.mkdir()
    result = materialize_candidate_source_bundle(bundle, source_root=source, workspace_root=root, contract_sha256=CONTRACT)
    assert result.workspace_path.is_dir()
    assert (result.workspace_path / "main.py").read_bytes().startswith(b"raise")
    assert (result.workspace_path / "lib/helper.py").read_bytes() == b"VALUE = 42\n"
    assert "workspace_path" not in result.to_dict()
    assert str(tmp_path) not in json.dumps(result.to_dict())
    assert result.file_table_sha256 == candidate_file_table_sha256(bundle)


def test_materialize_failure_removes_partial_directory(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    payload = _bundle(source)
    (source / "lib/helper.py").unlink()
    root = tmp_path / "workspaces"
    root.mkdir()
    with pytest.raises(CandidateWorkspaceError, match="^candidate_workspace_source_"):
        materialize_candidate_source_bundle(payload, source_root=source, workspace_root=root, contract_sha256=CONTRACT)
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(command=["relative-runner"]),
    lambda p: p.update(workspace_cwd="run"),
    lambda p: p.update(environment={"BAD=KEY": "x"}),
    lambda p: p.update(file_table_sha256="short"),
])
def test_workspace_plan_is_strict_and_replayed(mutation, tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    bundle = parse_candidate_source_bundle(_bundle(source))
    plan = build_candidate_workspace_plan(bundle, command=["/usr/bin/python", "main.py"], contract_sha256=CONTRACT)
    payload = plan.to_dict()
    mutation(payload)
    with pytest.raises(CandidateWorkspaceError):
        parse_candidate_workspace_plan(payload)
    assert validate_candidate_workspace_plan(plan) == plan


def test_workspace_plan_digest_is_independent_of_environment_order(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    bundle = parse_candidate_source_bundle(_bundle(source))
    first = build_candidate_workspace_plan(bundle, command=["/usr/bin/python"], contract_sha256=CONTRACT, environment={"B": "2", "A": "1"})
    second = build_candidate_workspace_plan(bundle, command=["/usr/bin/python"], contract_sha256=CONTRACT, environment={"A": "1", "B": "2"})
    assert first.digest() == second.digest()
    assert first.entrypoint == "main.py"


def test_materialize_never_executes_entrypoint_or_initializes_home(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    marker = tmp_path / "executed"
    (source / "main.py").write_text(f"Path({marker!r}).write_text('bad')", encoding="utf-8")
    payload = _bundle(source)
    payload["files"][0] = _item("main.py", (source / "main.py").read_bytes())
    root = tmp_path / "workspaces"
    root.mkdir()
    result = materialize_candidate_source_bundle(payload, source_root=source, workspace_root=root, contract_sha256=CONTRACT)
    assert not marker.exists()
    assert result.workspace_path.exists()
