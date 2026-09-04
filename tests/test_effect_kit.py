import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import famou.effect_kit as effect_kit_module
from famou.cli import main
from famou.effect_adapters import EffectAdapterError, convert_fm_eval_baseline
from famou.effect_kit import EffectKitError, build_effect_kit
from famou.effect_trial import EffectTrialConfig, EffectTrialRunner, TrialSuite


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _make_case(root: Path, *, answer: int = 42) -> Path:
    (root / "data").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "instruction.md").write_text(
        "Read data/instance.json and write solution.json.", encoding="utf-8"
    )
    (root / "instruction_en.md").write_text("private alternate", encoding="utf-8")
    (root / "data" / "instance.json").write_text(
        json.dumps({"target": answer}), encoding="utf-8"
    )
    (root / "data" / ".DS_Store").write_bytes(b"ignored metadata")
    (root / "data" / "ignored.pyc").write_bytes(b"ignored cache")
    (root / "gt.json").write_text(json.dumps({"answer": answer}), encoding="utf-8")
    (root / "tests" / "extractor_agent.py").write_text(
        "print('extractor')\n", encoding="utf-8"
    )
    (root / "tests" / "evaluator.py").write_text(
        "print('evaluator')\n", encoding="utf-8"
    )
    return root


def _results(case_keys: list[str], experiment_id: str = "fmexp-attested") -> dict:
    return {
        "experiment": {"id": experiment_id},
        "results": [
            {
                "case": key,
                "run_index": 0,
                "projection_state": "ready",
                "evaluation_status": "scored",
                "extraction_status": "extracted",
                "validity_score": 1.0,
                "overall_score": 0.80,
            }
            for key in case_keys
        ],
    }


def test_effect_kit_is_deterministic_and_contains_only_public_projection(tmp_path: Path) -> None:
    source_a = _make_case(tmp_path / "sources" / "a")
    source_b = _make_case(tmp_path / "sources" / "b", answer=7)
    output = tmp_path / "kit"

    manifest = build_effect_kit(
        output,
        {"case-b": source_b, "case-a": source_a},
        owner_attested_content_equivalence=True,
    )

    suite_bytes = (output / "suite.json").read_bytes()
    suite = TrialSuite.from_dict(json.loads(suite_bytes))
    assert [case.key for case in suite.cases] == ["case-a", "case-b"]
    assert suite.benchmark.release_version.startswith("content-")
    assert manifest["identity_basis"] == "owner_attested_content_equivalent"
    assert manifest["owner_attested_content_equivalence"] is True
    assert manifest["suite_sha256"] == hashlib.sha256(suite_bytes).hexdigest()
    assert str(source_a) not in json.dumps(manifest)
    assert str(source_b) not in json.dumps(manifest)

    for key in ("case-a", "case-b"):
        projection = output / "cases" / key
        assert sorted(
            path.relative_to(projection).as_posix()
            for path in projection.rglob("*")
            if path.is_file()
        ) == ["data/instance.json", "instruction.md"]
        assert not (projection / "gt.json").exists()
        assert not (projection / "tests").exists()
        ledger = next(case for case in suite.cases if case.key == key).public_files
        for item in ledger:
            target = projection / item.path
            assert target.stat().st_size == item.size
            assert hashlib.sha256(target.read_bytes()).hexdigest() == item.sha256

    copied_a = tmp_path / "copied" / "a"
    copied_b = tmp_path / "copied" / "b"
    shutil.copytree(source_a, copied_a)
    shutil.copytree(source_b, copied_b)
    second = tmp_path / "second-kit"
    build_effect_kit(
        second,
        {"case-a": copied_a, "case-b": copied_b},
        owner_attested_content_equivalence=True,
    )
    assert (second / "suite.json").read_bytes() == suite_bytes
    assert (second / "kit.json").read_bytes() == (output / "kit.json").read_bytes()


def test_effect_kit_rejects_existing_partial_unsafe_and_lfs_inputs(tmp_path: Path) -> None:
    valid = _make_case(tmp_path / "valid")
    invalid = _make_case(tmp_path / "invalid")
    (invalid / "tests" / "evaluator.py").unlink()
    output = tmp_path / "partial"

    with pytest.raises(EffectKitError, match="evaluator"):
        build_effect_kit(output, {"valid": valid, "invalid": invalid})
    assert not output.exists()

    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "owner.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(EffectKitError, match="already exists"):
        build_effect_kit(existing, {"valid": valid})
    assert (existing / "owner.txt").read_text(encoding="utf-8") == "keep"

    lfs = _make_case(tmp_path / "lfs")
    (lfs / "data" / "instance.json").write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:" + "1" * 64 + "\nsize 123456\n",
        encoding="utf-8",
    )
    with pytest.raises(EffectKitError, match="LFS"):
        build_effect_kit(tmp_path / "lfs-kit", {"lfs": lfs})

    linked = _make_case(tmp_path / "linked")
    (linked / "data" / "instance.json").unlink()
    (linked / "data" / "instance.json").symlink_to(valid / "data" / "instance.json")
    with pytest.raises(EffectKitError, match="linked|link"):
        build_effect_kit(tmp_path / "linked-kit", {"linked": linked})

    unsafe_name = _make_case(tmp_path / "unsafe-name")
    (unsafe_name / "data" / "-option.json").write_text("{}", encoding="utf-8")
    with pytest.raises(EffectKitError, match="unsafe data filename"):
        build_effect_kit(tmp_path / "unsafe-name-kit", {"unsafe": unsafe_name})


def test_effect_kit_cleans_only_its_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_case(tmp_path / "source")
    output = tmp_path / "partial-kit"
    original_copy = effect_kit_module.shutil.copyfile

    def interrupted_copy(source_path: Path, target_path: Path) -> None:
        original_copy(source_path, target_path)
        raise OSError("injected copy interruption")

    monkeypatch.setattr(effect_kit_module.shutil, "copyfile", interrupted_copy)

    with pytest.raises(OSError, match="injected copy interruption"):
        build_effect_kit(output, {"fixture": source})
    assert not output.exists()


def test_effect_kit_cli_emits_bounded_relative_manifest(tmp_path: Path, capsys) -> None:
    source = _make_case(tmp_path / "case")
    output = tmp_path / "kit"

    status = main(
        [
            "effect-kit",
            str(output),
            "--case",
            f"fixture={source}",
            "--owner-attested-content-equivalence",
            "--json",
        ]
    )

    assert status == 0
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["identity_basis"] == "owner_attested_content_equivalent"
    assert emitted["cases"][0]["public_projection"] == "cases/fixture"
    assert str(source) not in json.dumps(emitted)
    assert TrialSuite.from_dict(json.loads((output / "suite.json").read_text()))


def test_attested_baseline_and_report_preserve_honest_comparability(tmp_path: Path) -> None:
    source = _make_case(tmp_path / "case")
    kit = tmp_path / "kit"
    build_effect_kit(
        kit,
        {"fixture": source},
        owner_attested_content_equivalence=True,
    )
    suite_path = kit / "suite.json"
    suite = json.loads(suite_path.read_text())
    baseline_path = tmp_path / "baseline.json"
    results_path = _write_json(tmp_path / "results.json", _results(["fixture"]))

    baseline = convert_fm_eval_baseline(
        results_path,
        suite_path,
        baseline_path,
        experiment_id="fmexp-attested",
        requested_model="model",
        effective_model="model",
        model_evidence="owner_attested",
        content_equivalence_attested=True,
    )

    assert baseline["authority"] == "owner_attested_content_equivalent"
    assert baseline["conclusion_eligibility"] == "ineligible"

    def executor(command, *, cwd, env, timeout):
        del command, env, timeout
        request = json.loads(Path(cwd, "request.json").read_text())
        receipt = Path(cwd, request["receipt_path"])
        if Path(cwd).name == "subject":
            payload = {
                "schema_version": "1",
                "mode": "normal",
                "status": "completed",
                "requested_model": "model",
                "effective_model": "model",
                "model_evidence": "owner_attested",
                "interaction_turns": 1,
                "usage": None,
            }
        else:
            payload = {
                "schema_version": "1",
                "status": "completed",
                "benchmark": suite["benchmark"],
                "evaluation_profile": suite["evaluation_profile"],
                "case": request["case"],
                "harness": request["harness"],
                "extraction_status": "completed",
                "validity_score": 1.0,
                "overall_score": 0.81,
                "quality_score": 0.81,
                "detail_metrics": {},
            }
        receipt.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess([], 0)

    report = EffectTrialRunner(
        suite_path,
        baseline_path,
        tmp_path / "trial",
        case_sources={"fixture": kit / "cases" / "fixture"},
        config=EffectTrialConfig(
            runs_per_case=1,
            timeout_seconds=10,
            requested_model="model",
            subject_command=(str(Path(sys.executable).resolve()),),
            harness_command=(str(Path(sys.executable).resolve()),),
        ),
        process_executor=executor,
    ).run().to_dict()

    assert report["milestone"]["achieved"] is True
    assert (
        report["comparability"]["kind"]
        == "descriptive_owner_attested_content_equivalent"
    )
    assert report["comparability"]["formal_conclusion_eligibility"] == "ineligible"
    assert (
        "historical_publication_equivalence_is_owner_attested"
        in report["comparability"]["limitations"]
    )


def test_attestation_rejects_conflicting_authority_or_eligibility(tmp_path: Path) -> None:
    source = _make_case(tmp_path / "case")
    kit = tmp_path / "kit"
    build_effect_kit(kit, {"fixture": source})
    results = _write_json(tmp_path / "results.json", _results(["fixture"]))

    with pytest.raises(EffectAdapterError, match="attestation"):
        convert_fm_eval_baseline(
            results,
            kit / "suite.json",
            tmp_path / "baseline-a.json",
            experiment_id="fmexp-attested",
            requested_model="model",
            effective_model="model",
            model_evidence="not_observable",
            authority="scientific",
            content_equivalence_attested=True,
        )
    with pytest.raises(EffectAdapterError, match="attestation"):
        convert_fm_eval_baseline(
            results,
            kit / "suite.json",
            tmp_path / "baseline-b.json",
            experiment_id="fmexp-attested",
            requested_model="model",
            effective_model="model",
            model_evidence="not_observable",
            conclusion_eligibility="eligible",
            content_equivalence_attested=True,
        )
