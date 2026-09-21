"""Static candidate source manifests do not import or evaluate source files."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from lunar_evolution.candidate_bundle import (
    CandidateBundleError,
    CandidateSourceBundle,
    CandidateSourceFile,
    parse_candidate_source_bundle,
    validate_candidate_source_bundle,
    verify_candidate_source_bundle,
)

CONTRACT_SHA = "a" * 64


def _file(path="main.py", content=b"print('hello')\n"):
    return {"path": path, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def _payload():
    return {
        "schema_version": "1",
        "protocol": "lunar-candidate-source-bundle-v1",
        "contract_sha256": CONTRACT_SHA,
        "entrypoint": "main.py",
        "files": [_file(), _file("lib/helper.py", b"ANSWER = 42\n")],
    }


def test_roundtrip_sorts_files_and_hashes_the_complete_manifest(tmp_path):
    payload = _payload()
    parsed = parse_candidate_source_bundle(payload)
    assert [item.path for item in parsed.files] == ["lib/helper.py", "main.py"]
    expected = copy.deepcopy(payload)
    expected["files"].sort(key=lambda item: item["path"])
    assert parsed.to_dict() == expected
    canonical = json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert parsed.digest() == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    payload["files"].reverse()
    assert parse_candidate_source_bundle(payload).digest() == parsed.digest()
    source = tmp_path / "bundle.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    assert parse_candidate_source_bundle(source) == parsed
    assert validate_candidate_source_bundle(parsed) == parsed


@pytest.mark.parametrize("field", ["contract_sha256", "entrypoint", "source_bytes", "source_path"])
def test_digest_binds_contract_entrypoint_and_every_file(field):
    payload = _payload()
    original = parse_candidate_source_bundle(payload).digest()
    if field == "contract_sha256":
        payload[field] = "b" * 64
    elif field == "entrypoint":
        payload[field] = "lib/helper.py"
    elif field == "source_bytes":
        payload["files"][1] = _file("lib/helper.py", b"ANSWER = 43\n")
    else:
        payload["files"][1]["path"] = "lib/other.py"
    assert parse_candidate_source_bundle(payload).digest() != original


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(unknown=True),
    lambda p: p.pop("protocol"),
    lambda p: p.update(protocol="lunar-candidate-source-bundle-v2"),
    lambda p: p.update(schema_version=1),
    lambda p: p.update(contract_sha256="A" * 64),
    lambda p: p.update(contract_sha256=None),
    lambda p: p.update(entrypoint="absent.py"),
    lambda p: p.update(files=[]),
    lambda p: p.update(files="main.py"),
    lambda p: p.update(files=[None]),
    lambda p: p.update(files=[_file(f"file{i}.py") for i in range(65)]),
    lambda p: p["files"][0].update(size=True),
    lambda p: p["files"][0].update(size=-1),
    lambda p: p["files"][0].update(size=1.5),
    lambda p: p["files"][0].update(size=1024 * 1024 + 1),
    lambda p: p["files"][0].update(sha256="sha256:" + "a" * 64),
    lambda p: p["files"][0].update(content="print(1)"),
])
def test_invalid_manifest_is_rejected(mutation):
    payload = _payload()
    mutation(payload)
    with pytest.raises(CandidateBundleError, match="^candidate_bundle_invalid$"):
        parse_candidate_source_bundle(payload)


@pytest.mark.parametrize("path", [
    "", ".", "..", "../outside.py", "lib/../main.py", "./main.py", "lib/./main.py",
    "/main.py", "//main.py", "lib//main.py", "main.py/", "C:main.py", "lib\\main.py",
    "a\x00.py", "a\n.py", "a\x7f.py", "a\u202e.py", "a\ud800.py", "e\u0301.py",
    ".git/config", "lib/.GiT/HEAD", "x" * 1025, "é" * 513,
])
def test_paths_must_be_normalized_and_portable(path):
    payload = _payload()
    payload["files"][1]["path"] = path
    with pytest.raises(CandidateBundleError, match="^candidate_bundle_path_unsafe$"):
        parse_candidate_source_bundle(payload)


@pytest.mark.parametrize("paths", [
    ("main.py", "main.py"),
    ("main.py", "MAIN.py"),
    ("main.py", "main.py/helper.py"),
    ("main.py/helper.py", "main.py"),
    ("main.py/helper.py", "MAIN.py"),
    ("lib/a.py", "LIB/b.py"),
    ("lib/pkg/a.py", "lib/PKG/b.py"),
    ("Straße/a.py", "STRASSE/b.py"),
])
def test_duplicate_paths_file_directory_conflicts_and_directory_aliases_are_rejected(paths):
    payload = _payload()
    payload["entrypoint"] = paths[0]
    payload["files"] = [_file(path) for path in paths]
    with pytest.raises(CandidateBundleError, match="^candidate_bundle_path_unsafe$"):
        parse_candidate_source_bundle(payload)


def test_normal_hidden_files_empty_sources_and_nfc_paths_are_supported(tmp_path):
    paths = ("main.py", "lib/.hidden.py", "lib/é.py")
    payload = _payload()
    payload["files"] = [_file(path, b"") for path in paths]
    for path in paths:
        source = tmp_path / path
        source.parent.mkdir(exist_ok=True)
        source.write_bytes(b"")
    result = verify_candidate_source_bundle(payload, source_root=tmp_path, contract_sha256=CONTRACT_SHA)
    assert result.total_bytes == 0
    assert result.file_count == 3


def test_file_and_total_manifest_limits_are_independent():
    payload = _payload()
    payload["files"] = [_file("main.py", b"")] + [_file(f"lib/{i}.py", b"") for i in range(63)]
    for item in payload["files"][:16]:
        item["size"] = 1024 * 1024
    assert len(parse_candidate_source_bundle(payload).files) == 64
    payload["files"][16]["size"] = 1
    with pytest.raises(CandidateBundleError, match="^candidate_bundle_invalid$"):
        parse_candidate_source_bundle(payload)


@pytest.mark.parametrize("content", [
    b'{"schema_version":"1","schema_version":"1"}',
    b'{"files":[{"path":"x","path":"x"}]}',
    b'{"files":NaN}', b'{"files":Infinity}', b'{"files":-Infinity}',
    b"\xff", b"", b"[]", b"null", b"{" * 1000,
])
def test_file_parser_rejects_non_strict_json(tmp_path, content):
    source = tmp_path / "manifest.json"
    source.write_bytes(content)
    with pytest.raises(CandidateBundleError, match="^candidate_bundle_invalid$"):
        parse_candidate_source_bundle(source)


def test_verify_checks_declared_sources_without_importing_or_scanning(tmp_path, monkeypatch):
    content = b"raise RuntimeError('never execute candidate')\n"
    (tmp_path / "main.py").write_bytes(content)
    (tmp_path / "undeclared.bin").write_bytes(b"\x00\xff")
    payload = _payload()
    payload["files"] = [_file(content=content)]
    bundle = parse_candidate_source_bundle(payload)
    monkeypatch.setattr(Path, "rglob", lambda *_: pytest.fail("scanned undeclared files"))
    verified = verify_candidate_source_bundle(
        bundle, source_root=tmp_path, contract_sha256=CONTRACT_SHA,
        expected_bundle_sha256=bundle.digest(),
    )
    assert verified.bundle == bundle
    assert verified.bundle_sha256 == bundle.digest()
    assert verified.file_count == 1
    assert verified.total_bytes == len(content)
    assert "never execute" not in repr(verified)


@pytest.mark.parametrize(("pins", "error"), [
    ({"contract_sha256": "b" * 64}, "contract_mismatch"),
    ({"contract_sha256": None}, "invalid"),
    ({"contract_sha256": "short"}, "invalid"),
    ({"expected_bundle_sha256": "b" * 64}, "identity_mismatch"),
    ({"expected_bundle_sha256": "short"}, "invalid"),
])
def test_bad_caller_pins_are_rejected_before_reading_sources(monkeypatch, pins, error):
    options = {"contract_sha256": CONTRACT_SHA, **pins}
    monkeypatch.setattr(os, "open", lambda *_a, **_kw: pytest.fail("read before pin validation"))
    with pytest.raises(CandidateBundleError, match=f"^candidate_bundle_{error}$"):
        verify_candidate_source_bundle(_payload(), source_root="unused", **options)


@pytest.mark.parametrize("mutation", [
    lambda b: object.__setattr__(b, "entrypoint", "absent.py"),
    lambda b: object.__setattr__(b, "protocol", "changed"),
    lambda b: object.__setattr__(b, "files", None),
    lambda b: object.__setattr__(b.files[0], "size", True),
    lambda b: object.__setattr__(b.files[0], "path", "../outside.py"),
])
def test_typed_objects_are_rebuilt_before_source_reads(monkeypatch, mutation):
    bundle = parse_candidate_source_bundle(_payload())
    mutation(bundle)
    monkeypatch.setattr(os, "open", lambda *_a, **_kw: pytest.fail("invalid DTO opened files"))
    with pytest.raises(CandidateBundleError):
        verify_candidate_source_bundle(bundle, source_root="unused", contract_sha256=CONTRACT_SHA)
    with pytest.raises(CandidateBundleError):
        validate_candidate_source_bundle(bundle)


@pytest.mark.parametrize("content", [b"\xff", b"print('x')\x00\n"])
def test_valid_digests_do_not_make_binary_source_valid(tmp_path, content):
    payload = _payload()
    payload["files"] = [_file(content=content)]
    (tmp_path / "main.py").write_bytes(content)
    with pytest.raises(CandidateBundleError, match="^candidate_bundle_source_encoding_invalid$"):
        verify_candidate_source_bundle(payload, source_root=tmp_path, contract_sha256=CONTRACT_SHA)


def test_source_digest_mismatch_is_rejected(tmp_path):
    payload = _payload()
    payload["files"] = [_file()]
    (tmp_path / "main.py").write_bytes(b"print('other')\n")
    with pytest.raises(CandidateBundleError, match="^candidate_bundle_source_changed$"):
        verify_candidate_source_bundle(payload, source_root=tmp_path, contract_sha256=CONTRACT_SHA)


def test_direct_construction_defensively_copies_file_entries():
    source = CandidateSourceFile(**_file())
    files = [source]
    bundle = CandidateSourceBundle(CONTRACT_SHA, "main.py", files)
    files.clear()
    object.__setattr__(source, "size", 999)
    assert isinstance(bundle.files, tuple)
    assert bundle.files[0].size == len(b"print('hello')\n")


@pytest.mark.parametrize("value", [None, [], 3, object()])
def test_invalid_public_api_types_have_fixed_errors(value):
    with pytest.raises(CandidateBundleError, match="^candidate_bundle_invalid$"):
        parse_candidate_source_bundle(value)
    with pytest.raises(CandidateBundleError, match="^candidate_bundle_invalid$"):
        validate_candidate_source_bundle(value)
