"""Static source bundle verification exposes only bounded metadata and fixed errors."""

import hashlib
import json
import os
from pathlib import Path

import pytest
from test_cli import _write_evolution_contract

from lunar_evolution import cli
from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.candidate_bundle import MAX_CANDIDATE_BUNDLE_BYTES, CandidateSourceBundle


def _cli_files(tmp_path: Path):
    contract_path = tmp_path / "private-contract.json"
    _write_evolution_contract(contract_path)
    contract = AlgorithmProblemContract.from_dict(json.loads(contract_path.read_text()))
    source_root = tmp_path / "private-source-root"
    source_dir = source_root / "src"
    source_dir.mkdir(parents=True)
    marker = tmp_path / "private-source-was-executed"
    sources = {
        "src/private-main.py": (
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
            "# private-source-content-must-not-be-printed\n"
        ).encode(),
        "src/private-helper.py": b"def helper():\n    return 'private-helper-value'\n",
    }
    for relative_path, content in sources.items():
        (source_root / relative_path).write_bytes(content)
    payload = {
        "schema_version": "1",
        "protocol": "lunar-candidate-source-bundle-v1",
        "contract_sha256": contract.digest(),
        "entrypoint": "src/private-main.py",
        "files": [
            {"path": relative_path, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            for relative_path, content in sources.items()
        ],
    }
    manifest_path = tmp_path / "private-manifest.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    bundle = CandidateSourceBundle.from_dict(payload)
    home = tmp_path / "private-home-must-not-be-created"
    args = [
        "candidate-bundle", "validate", str(manifest_path),
        "--source-root", str(source_root), "--contract", str(contract_path), "--home", str(home),
    ]
    return args, manifest_path, contract_path, source_root, bundle, marker, home


def _forbid_initialization(monkeypatch):
    def unexpected_initialization(*_args, **_kwargs):
        pytest.fail("source bundle validation initialized home or Store")

    monkeypatch.setattr(cli, "_config", unexpected_initialization)
    monkeypatch.setattr(cli.Config, "ensure", unexpected_initialization)
    monkeypatch.setattr(cli.Store, "__init__", unexpected_initialization)
    monkeypatch.setattr(cli.Store, "initialize", unexpected_initialization)


def _assert_redacted(output, tmp_path):
    combined = output.out + output.err
    assert str(tmp_path) not in combined
    assert "private-" not in combined
    assert "write_text" not in combined


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize("pinned", [False, True])
def test_cli_verifies_two_sources_without_execution_or_initialization(
    tmp_path, monkeypatch, capsys, json_mode, pinned,
):
    args, manifest, contract, source_root, bundle, marker, home = _cli_files(tmp_path)
    _forbid_initialization(monkeypatch)
    if pinned:
        args.extend(["--bundle-sha256", bundle.digest()])
    if json_mode:
        args.append("--json")
    input_paths = [manifest, contract, *(source_root / source.path for source in bundle.files)]
    originals = {
        source_path: (source_path.read_bytes(), source_path.stat().st_mtime_ns)
        for source_path in input_paths
    }

    assert cli.main(args) == 0
    output = capsys.readouterr()
    assert output.err == ""
    if json_mode:
        assert json.loads(output.out) == {
            "status": "validated",
            "bundle_sha256": bundle.digest(),
            "contract_sha256": bundle.contract_sha256,
            "file_count": 2,
            "total_bytes": sum(source.size for source in bundle.files),
        }
    else:
        assert bundle.digest() in output.out
        assert bundle.contract_sha256 in output.out
        assert "validated" in output.out
    _assert_redacted(output, tmp_path)
    assert not marker.exists()
    assert not home.exists()
    assert not list(tmp_path.rglob("state.db"))
    assert originals == {
        source_path: (source_path.read_bytes(), source_path.stat().st_mtime_ns)
        for source_path in input_paths
    }


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize(("failure", "error_code"), [
    ("helper_changed", "candidate_bundle_source_changed"),
    ("helper_missing", "candidate_bundle_source_missing"),
    ("contract_mismatch", "candidate_bundle_contract_mismatch"),
    ("bundle_mismatch", "candidate_bundle_identity_mismatch"),
    ("bundle_invalid", "candidate_bundle_invalid"),
    ("manifest_symlink", "candidate_bundle_invalid"),
    ("manifest_fifo", "candidate_bundle_invalid"),
    ("manifest_malformed", "candidate_bundle_invalid"),
    ("manifest_too_large", "candidate_bundle_too_large"),
    ("contract_symlink", "candidate_bundle_contract_invalid"),
    ("contract_fifo", "candidate_bundle_contract_invalid"),
    ("contract_malformed", "candidate_bundle_contract_invalid"),
    ("contract_too_large", "candidate_bundle_contract_invalid"),
])
def test_cli_bundle_failures_are_fixed_static_and_redacted(
    tmp_path, monkeypatch, capsys, json_mode, failure, error_code,
):
    args, manifest, contract, source_root, bundle, marker, home = _cli_files(tmp_path)
    helper = source_root / "src/private-helper.py"
    if failure == "helper_changed":
        # Keep the byte count identical so this checks the content digest, too.
        helper.write_bytes(helper.read_bytes().replace(b"helper-value", b"helper-other"))
    elif failure == "helper_missing":
        helper.unlink()
    elif failure == "contract_mismatch":
        payload = json.loads(contract.read_text())
        payload["problem_id"] = "private-different-contract"
        contract.write_text(json.dumps(payload))
        helper.unlink()  # Caller pins must fail before source IO.
    elif failure in {"bundle_mismatch", "bundle_invalid"}:
        supplied_pin = "f" * 64 if failure == "bundle_mismatch" else "private-invalid-pin"
        assert supplied_pin != bundle.digest()
        args.extend(["--bundle-sha256", supplied_pin])
        helper.unlink()
    else:
        target = manifest if failure.startswith("manifest_") else contract
        mutation = failure.split("_", 1)[1]
        if mutation == "symlink":
            outside = tmp_path / ("private-linked-" + target.name)
            target.rename(outside)
            target.symlink_to(outside)
        elif mutation == "fifo":
            target.unlink()
            os.mkfifo(target)
        elif mutation == "malformed":
            target.write_text("{private-malformed-input")
        else:
            assert mutation == "too_large"
            bound = MAX_CANDIDATE_BUNDLE_BYTES if target == manifest else cli.MAX_CONTRACT_BYTES
            target.write_bytes(b" " * (bound + 1))
    _forbid_initialization(monkeypatch)
    if json_mode:
        args.append("--json")

    assert cli.main(args) == 2
    output = capsys.readouterr()
    assert output.out == ""
    if json_mode:
        assert json.loads(output.err) == {"error": error_code}
    else:
        assert output.err == f"error: {error_code}\n"
    _assert_redacted(output, tmp_path)
    assert not marker.exists()
    assert not home.exists()
    assert not list(tmp_path.rglob("state.db"))
