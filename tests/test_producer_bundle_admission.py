from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from lunar_evolution import (
    ProducerBundleAdmissionError,
    ProducerBundleAdmissionItem,
    build_producer_bundle_admission_plan,
    parse_producer_bundle_admission_plan,
)
from lunar_evolution.evolution import CandidateDraft
from lunar_evolution.producer_bundle_population import prepare_producer_bundle_drafts
from tests.test_producer_bundle_population import _contract, _verified_bundle

AUTHORITY = {
    "contract_sha256": _contract().digest(),
    "evaluator_kind": "exact_harness",
    "evaluator_fingerprint": "b" * 64,
    "runner_fingerprint": "c" * 64,
    "dependency_sha256": "d" * 64,
    "environment_sha256": "e" * 64,
}


def _plan(drafts):
    return build_producer_bundle_admission_plan(drafts, **AUTHORITY)


def _provenance_draft(draft, **changes):
    """Return a detached draft with a matching producer provenance projection."""
    values = {
        "bundle_id": draft.bundle_id,
        "bundle_sha256": draft.bundle_sha256,
        "producer_fingerprint": draft.producer_fingerprint,
        "producer_id": draft.producer_id,
        "envelope_sha256": draft.envelope_sha256,
    }
    values.update(changes)
    metadata = {"producer_bundle": values.copy()}
    native = CandidateDraft.from_files(dict(draft.draft.source_files), draft.entrypoint, metadata)
    return replace(
        draft,
        draft=native,
        bundle_id=values["bundle_id"],
        bundle_sha256=values["bundle_sha256"],
        producer_fingerprint=values["producer_fingerprint"],
        producer_id=values["producer_id"],
        envelope_sha256=values["envelope_sha256"],
    )


def test_builds_stable_ordered_plan_without_writing(tmp_path: Path) -> None:
    first = _verified_bundle(tmp_path, bundle_id="first", prefix="first")
    second = _verified_bundle(tmp_path, bundle_id="second", prefix="second")
    drafts = prepare_producer_bundle_drafts(tmp_path, [first, second])
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    plan = _plan(drafts)

    assert [item.bundle_id for item in plan.bundles] == ["first", "second"]
    assert plan.bundles[0].bundle_sha256 == plan.bundles[0].draft_bundle_sha256
    assert len(plan.digest()) == 64
    assert "quality" not in plan.to_dict()
    assert sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")) == before
    assert _plan(drafts).to_dict() == plan.to_dict()
    assert _plan(drafts).digest() == plan.digest()


def test_rejects_duplicate_ids_and_paths(tmp_path: Path) -> None:
    bundle = _verified_bundle(tmp_path)
    draft = prepare_producer_bundle_drafts(tmp_path, [bundle])[0]

    with pytest.raises(ProducerBundleAdmissionError) as caught:
        _plan([draft, draft])
    assert caught.value.code == "producer_bundle_admission_id_duplicate"

    second = _provenance_draft(draft, bundle_id="second")
    with pytest.raises(ProducerBundleAdmissionError) as caught:
        _plan([draft, second])
    assert caught.value.code == "producer_bundle_admission_path_reused"


def test_rejects_contract_or_draft_digest_mismatch(tmp_path: Path) -> None:
    bundle = _verified_bundle(tmp_path)
    draft = prepare_producer_bundle_drafts(tmp_path, [bundle])[0]

    with pytest.raises(ProducerBundleAdmissionError) as caught:
        build_producer_bundle_admission_plan(
            [draft], **{**AUTHORITY, "contract_sha256": "f" * 64}
        )
    assert caught.value.code == "producer_bundle_admission_bundle_mismatch"

    altered = replace(
        draft,
        draft=CandidateDraft.from_files(
            {**draft.draft.source_files, "pkg/helper.py": "VALUE = 2\n"},
            draft.entrypoint,
            dict(draft.draft.metadata),
        ),
    )
    with pytest.raises(ProducerBundleAdmissionError) as caught:
        _plan([altered])
    assert caught.value.code == "producer_bundle_admission_bundle_mismatch"


def test_rejects_provenance_tampering_and_invalid_inputs(tmp_path: Path) -> None:
    bundle = _verified_bundle(tmp_path)
    draft = prepare_producer_bundle_drafts(tmp_path, [bundle])[0]
    metadata = dict(draft.draft.metadata)
    producer = dict(metadata["producer_bundle"])
    producer["producer_id"] = "changed"
    altered = replace(
        draft,
        draft=CandidateDraft.from_files(
            dict(draft.draft.source_files), draft.entrypoint, {"producer_bundle": producer}
        ),
    )
    with pytest.raises(ProducerBundleAdmissionError) as caught:
        _plan([altered])
    assert caught.value.code == "producer_bundle_admission_provenance_invalid"

    with pytest.raises(ProducerBundleAdmissionError) as caught:
        build_producer_bundle_admission_plan([object()], **AUTHORITY)  # type: ignore[list-item]
    assert caught.value.code == "producer_bundle_admission_draft_invalid"

    with pytest.raises(ProducerBundleAdmissionError) as caught:
        build_producer_bundle_admission_plan([draft], **{**AUTHORITY, "runner_fingerprint": "x"})
    assert caught.value.code == "producer_bundle_admission_runner_invalid"


def test_identity_order_and_authority_are_bound_to_plan_digest(tmp_path: Path) -> None:
    first = _verified_bundle(tmp_path, bundle_id="first", prefix="first")
    second = _verified_bundle(tmp_path, bundle_id="second", prefix="second")
    drafts = prepare_producer_bundle_drafts(tmp_path, [first, second])
    baseline = _plan(drafts)

    assert baseline.digest() != _plan(list(reversed(drafts))).digest()
    identity = _provenance_draft(drafts[0], producer_fingerprint="f" * 64)
    assert _plan([identity, drafts[1]]).digest() != baseline.digest()

    for field in ("evaluator_kind", "evaluator_fingerprint", "runner_fingerprint", "dependency_sha256", "environment_sha256"):
        changed = dict(AUTHORITY)
        changed[field] = "other_kind" if field == "evaluator_kind" else "f" * 64
        assert build_producer_bundle_admission_plan(drafts, **changed).digest() != baseline.digest()


def test_reordered_source_maps_have_canonical_bundle_identity(tmp_path: Path) -> None:
    bundle = _verified_bundle(tmp_path)
    draft = prepare_producer_bundle_drafts(tmp_path, [bundle])[0]
    files = dict(reversed(tuple(draft.draft.source_files.items())))
    reordered = replace(
        draft,
        draft=CandidateDraft.from_files(files, draft.entrypoint, dict(draft.draft.metadata)),
    )

    assert _plan([reordered]).digest() == _plan([draft]).digest()


def test_mutable_source_and_provenance_are_revalidated(tmp_path: Path) -> None:
    bundle = _verified_bundle(tmp_path)
    draft = prepare_producer_bundle_drafts(tmp_path, [bundle])[0]
    draft.draft.source_files["pkg/helper.py"] = "VALUE = 2\n"
    with pytest.raises(ProducerBundleAdmissionError) as caught:
        _plan([draft])
    assert caught.value.code == "producer_bundle_admission_bundle_mismatch"

    bundle = _verified_bundle(tmp_path, bundle_id="second", prefix="other")
    draft = prepare_producer_bundle_drafts(tmp_path, [bundle])[0]
    draft.draft.metadata["producer_bundle"]["producer_id"] = "changed"
    with pytest.raises(ProducerBundleAdmissionError) as caught:
        _plan([draft])
    assert caught.value.code == "producer_bundle_admission_provenance_invalid"


def test_direct_admission_item_rejects_unsafe_path_and_digest_mismatch() -> None:
    kwargs = {
        "bundle_id": "bundle",
        "bundle_sha256": "a" * 64,
        "draft_bundle_sha256": "b" * 64,
        "entrypoint": "pkg/main.py",
        "material_paths": ("../escape.py", "pkg/main.py"),
        "producer_fingerprint": "c" * 64,
    }
    with pytest.raises(ProducerBundleAdmissionError) as caught:
        ProducerBundleAdmissionItem(**kwargs)
    assert caught.value.code == "producer_bundle_admission_paths_invalid"

    kwargs["material_paths"] = ("pkg/main.py",)
    with pytest.raises(ProducerBundleAdmissionError) as caught:
        ProducerBundleAdmissionItem(**kwargs)
    assert caught.value.code == "producer_bundle_admission_bundle_mismatch"


def test_mutated_nested_item_produces_fixed_digest_error(tmp_path: Path) -> None:
    bundle = _verified_bundle(tmp_path)
    draft = prepare_producer_bundle_drafts(tmp_path, [bundle])[0]
    plan = _plan([draft])
    object.__setattr__(plan.bundles[0], "bundle_id", object())

    with pytest.raises(ProducerBundleAdmissionError) as caught:
        plan.digest()
    assert caught.value.code == "producer_bundle_admission_canonical_invalid"


def test_rejects_invalid_or_extra_provenance_metadata(tmp_path: Path) -> None:
    bundle = _verified_bundle(tmp_path)
    draft = prepare_producer_bundle_drafts(tmp_path, [bundle])[0]
    metadata = {"producer_bundle": list(draft.draft.metadata["producer_bundle"].items())}
    altered = replace(
        draft,
        draft=CandidateDraft.from_files(dict(draft.draft.source_files), draft.entrypoint, metadata),
    )
    with pytest.raises(ProducerBundleAdmissionError) as caught:
        _plan([altered])
    assert caught.value.code == "producer_bundle_admission_provenance_invalid"

    metadata = {"producer_bundle": {**draft.draft.metadata["producer_bundle"], "extra": "x"}}
    altered = replace(
        draft,
        draft=CandidateDraft.from_files(dict(draft.draft.source_files), draft.entrypoint, metadata),
    )
    with pytest.raises(ProducerBundleAdmissionError) as caught:
        _plan([altered])
    assert caught.value.code == "producer_bundle_admission_provenance_invalid"


def test_parse_roundtrip_and_rejects_duplicate_unknown_or_oversized_json(tmp_path: Path) -> None:
    bundle = _verified_bundle(tmp_path, bundle_id="parse")
    draft = prepare_producer_bundle_drafts(tmp_path, [bundle])[0]
    plan = _plan([draft])
    payload = plan.to_dict()

    assert parse_producer_bundle_admission_plan(payload).digest() == plan.digest()
    path = tmp_path / "admission.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert parse_producer_bundle_admission_plan(path).to_dict() == payload

    unknown = dict(payload)
    unknown["unknown"] = True
    with pytest.raises(ProducerBundleAdmissionError) as caught:
        parse_producer_bundle_admission_plan(unknown)
    assert caught.value.code == "producer_bundle_admission_schema_invalid"

    encoded = json.dumps(payload, separators=(",", ":"))
    duplicate = encoded[:-1] + ',"protocol":' + json.dumps(payload["protocol"]) + "}"
    path.write_text(duplicate, encoding="utf-8")
    with pytest.raises(ProducerBundleAdmissionError) as caught:
        parse_producer_bundle_admission_plan(path)
    assert caught.value.code == "producer_bundle_admission_plan_invalid"

    path.write_bytes(b"{" + b"x" * (128 * 1024) + b"}")
    with pytest.raises(ProducerBundleAdmissionError) as caught:
        parse_producer_bundle_admission_plan(path)
    assert caught.value.code == "producer_bundle_admission_too_large"
