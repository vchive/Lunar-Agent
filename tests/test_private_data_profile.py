import hashlib
import json
from pathlib import Path

import pytest

from famou.algorithm import AlgorithmProblemContract
from famou.data_profile import (
    DataProfileError,
    build_private_input_profile,
    canonical_profile_json,
    profile_sha256,
)
from famou.evolution import CandidateInputArtifact


def _contract(path: str, format_name: str, fields: dict[str, str]) -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "profile-fixture",
            "problem_type": "routing",
            "statement": "Profile exact input structure without disclosing values.",
            "inputs": [{"path": path, "format": format_name, "fields": fields}],
            "decision_variables": ["assignment"],
            "objective": {"name": "cost", "direction": "minimize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["Produce a valid assignment."],
            "deliverables": ["assignment table"],
        }
    )


def _stage(root: Path, name: str, content: str) -> CandidateInputArtifact:
    path = root / "data" / "raw" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return CandidateInputArtifact(
        f"data/raw/{name}",
        path.stat().st_size,
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def test_csv_profile_contains_structure_not_values(tmp_path: Path) -> None:
    secret = "customer-secret-sk-abcdefghijklmnop"
    descriptor = _stage(
        tmp_path,
        "orders.csv",
        f"order_id,cost,note\na,10,{secret}\nb,,ordinary\nb,12,ordinary\n",
    )
    profile = build_private_input_profile(
        tmp_path,
        _contract(
            "orders.csv",
            "csv",
            {"order_id": "identifier", "cost": "cost", "note": "note"},
        ),
        (descriptor,),
    )

    assert profile["schema_version"] == "1"
    file_profile = profile["files"][0]
    assert file_profile["path"] == "data/raw/orders.csv"
    assert file_profile["row_count"] == 3
    assert file_profile["size"] == descriptor.size
    assert file_profile["sha256"] == descriptor.sha256
    assert file_profile["fields"] == [
        {"name": "order_id", "type": "string", "null_count": 0, "unique_count": 2},
        {"name": "cost", "type": "string", "null_count": 1, "unique_count": 2},
        {"name": "note", "type": "string", "null_count": 0, "unique_count": 2},
    ]
    encoded = json.dumps(profile, ensure_ascii=False)
    assert secret not in encoded
    assert "ordinary" not in encoded
    assert str(tmp_path) not in encoded
    assert all(key not in encoded for key in ('"sample"', '"minimum"', '"maximum"'))
    assert profile_sha256(profile) == profile_sha256(profile)
    canonical = canonical_profile_json(profile)
    assert "\n" not in canonical
    assert profile_sha256(profile) == hashlib.sha256(canonical.encode()).hexdigest()


@pytest.mark.parametrize(
    ("format_name", "name", "content", "expected"),
    [
        (
            "json",
            "records.json",
            (
                '[{"id":1,"active":true,"score":1.5,"meta":{},"tags":[]},'
                '{"id":2,"active":null,"score":2,"meta":{},"tags":[]}]'
            ),
            {
                "active": ("boolean", 1, 1),
                "id": ("integer", 0, 2),
                "meta": ("object", 0, 1),
                "score": ("mixed", 0, 2),
                "tags": ("array", 0, 1),
            },
        ),
        (
            "jsonl",
            "records.jsonl",
            '{"id":"001","value":null}\n{"id":"002","value":"3"}\n',
            {"id": ("string", 0, 2), "value": ("string", 1, 1)},
        ),
    ],
)
def test_structured_profiles_use_conservative_types(
    tmp_path: Path,
    format_name: str,
    name: str,
    content: str,
    expected: dict[str, tuple[str, int, int]],
) -> None:
    descriptor = _stage(tmp_path, name, content)
    profile = build_private_input_profile(
        tmp_path,
        _contract(name, format_name, {key: key for key in expected}),
        (descriptor,),
    )
    fields = {
        item["name"]: (item["type"], item["null_count"], item["unique_count"])
        for item in profile["files"][0]["fields"]
    }
    assert fields == expected
    assert profile["files"][0]["row_count"] == 2
    assert "001" not in json.dumps(profile)
    assert "002" not in json.dumps(profile)


def test_text_profile_exposes_only_line_and_byte_counts(tmp_path: Path) -> None:
    descriptor = _stage(tmp_path, "notes.txt", "private first line\nprivate second line\n")
    profile = build_private_input_profile(
        tmp_path,
        _contract("notes.txt", "text", {"content": "opaque text"}),
        (descriptor,),
    )
    file_profile = profile["files"][0]
    assert file_profile["line_count"] == 2
    assert file_profile["fields"] == []
    assert "private" not in json.dumps(profile)


@pytest.mark.parametrize(
    "mode",
    [
        "digest",
        "duplicate_header",
        "duplicate_json_key",
        "non_finite_json",
        "malformed_json",
        "unsupported",
    ],
)
def test_profile_fails_closed_on_untrusted_or_ambiguous_data(
    tmp_path: Path, mode: str
) -> None:
    if mode == "duplicate_header":
        descriptor = _stage(tmp_path, "input.csv", "id,id\na,b\n")
        contract = _contract("input.csv", "csv", {"id": "identifier"})
    elif mode == "malformed_json":
        descriptor = _stage(tmp_path, "input.json", "{not-json")
        contract = _contract("input.json", "json", {"id": "identifier"})
    elif mode == "duplicate_json_key":
        descriptor = _stage(tmp_path, "input.json", '{"id":1,"id":2}')
        contract = _contract("input.json", "json", {"id": "identifier"})
    elif mode == "non_finite_json":
        descriptor = _stage(tmp_path, "input.json", '{"id":NaN}')
        contract = _contract("input.json", "json", {"id": "identifier"})
    elif mode == "unsupported":
        descriptor = _stage(tmp_path, "input.yaml", "id: private")
        contract = _contract("input.yaml", "yaml", {"id": "identifier"})
    else:
        descriptor = _stage(tmp_path, "input.csv", "id\na\n")
        descriptor = CandidateInputArtifact(descriptor.path, descriptor.size, "0" * 64)
        contract = _contract("input.csv", "csv", {"id": "identifier"})

    with pytest.raises(DataProfileError):
        build_private_input_profile(tmp_path, contract, (descriptor,))


def test_profile_rejects_symlink_and_contract_descriptor_mismatch(tmp_path: Path) -> None:
    descriptor = _stage(tmp_path, "input.csv", "id\na\n")
    source = tmp_path / descriptor.path
    outside = tmp_path / "outside.csv"
    outside.write_text(source.read_text(), encoding="utf-8")
    source.unlink()
    source.symlink_to(outside)
    with pytest.raises(DataProfileError, match="symlink"):
        build_private_input_profile(
            tmp_path, _contract("input.csv", "csv", {"id": "identifier"}), (descriptor,)
        )

    other_root = tmp_path / "other"
    extra = _stage(other_root, "extra.csv", "id\na\n")
    with pytest.raises(DataProfileError, match="declared"):
        build_private_input_profile(
            other_root,
            _contract("input.csv", "csv", {"id": "identifier"}),
            (extra,),
        )


@pytest.mark.parametrize(
    ("format_name", "name", "content", "message"),
    [
        ("csv", "input.csv", "id,name\n1\n", "row width"),
        ("jsonl", "input.jsonl", "{}\n[]\n", "must be objects"),
        (
            "json",
            "input.json",
            '{"root":{"a":{"b":{"c":{"d":{"e":{"f":{"g":{"h":{"i":{"j":{"k":{"l":{"m":{"n":{"o":1}}}}}}}}}}}}}}}}',
            "nesting limit",
        ),
    ],
)
def test_profile_rejects_ambiguous_rows_and_excessive_nesting(
    tmp_path: Path,
    format_name: str,
    name: str,
    content: str,
    message: str,
) -> None:
    descriptor = _stage(tmp_path, name, content)
    with pytest.raises(DataProfileError, match=message):
        build_private_input_profile(
            tmp_path, _contract(name, format_name, {"id": "identifier"}), (descriptor,)
        )


def test_profile_rejects_invalid_utf8_and_secret_field_names(tmp_path: Path) -> None:
    path = tmp_path / "data" / "raw" / "input.csv"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"id\n\xff\n")
    invalid = CandidateInputArtifact(
        "data/raw/input.csv", path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest()
    )
    with pytest.raises(DataProfileError, match="UTF-8"):
        build_private_input_profile(
            tmp_path, _contract("input.csv", "csv", {"id": "identifier"}), (invalid,)
        )

    secret = "sk-abcdefghijklmnop"
    descriptor = _stage(tmp_path, "input.csv", f"id,{secret}\na,b\n")
    with pytest.raises(DataProfileError, match="credential"):
        build_private_input_profile(
            tmp_path, _contract("input.csv", "csv", {"id": "identifier"}), (descriptor,)
        )
