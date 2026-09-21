from __future__ import annotations

import hashlib
import json
import shlex
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from lunar_evolution.cli import main
from lunar_evolution.store import Store

PRODUCER_FINGERPRINT = "b" * 64
GOOD_SOURCE = "# producer-good\ndef solve():\n    return 42\n"
BAD_SOURCE = "# producer-bad\ndef solve():\n    return -1\n"


@dataclass(frozen=True)
class ProducerCase:
    root: Path
    contract: Path
    native: Path
    exported: Path
    generator: Path
    evaluator: Path
    generator_calls: Path
    evaluator_calls: Path

    @property
    def home(self) -> Path:
        return self.root / "home"

    @property
    def workspace(self) -> Path:
        return self.root / "workspace"

    def evolve_arguments(self) -> list[str]:
        return [
            "evolve", str(self.contract),
            "--producer-result", str(self.exported),
            "--producer-fingerprint", PRODUCER_FINGERPRINT,
            "--producer-id", "shinka",
            "--generator-command", shlex.join((sys.executable, str(self.generator))),
            "--evaluator-command", shlex.join((sys.executable, str(self.evaluator))),
            "--population-size", "1",
            "--offspring-per-iteration", "1",
            "--islands", "1",
            "--workspace", str(self.workspace),
            "--home", str(self.home),
            "--json",
        ]


@pytest.fixture
def producer_case(tmp_path: Path) -> ProducerCase:
    contract = tmp_path / "contract.json"
    contract.write_text(
        json.dumps({
            "schema_version": "1",
            "problem_id": "producer-cli-integration",
            "problem_type": "routing",
            "statement": "Find a deterministic route.",
            "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "item id"}}],
            "decision_variables": ["route order"],
            "objective": {"name": "quality", "direction": "maximize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["All items are served."],
            "deliverables": ["A route program."],
            "evolution": {
                "strategy": "population", "max_rounds": 1, "stagnation_rounds": 10,
            },
        }),
        encoding="utf-8",
    )
    native = tmp_path / "native"
    native.mkdir()
    with sqlite3.connect(native / "programs.sqlite") as connection:
        connection.execute(
            "CREATE TABLE programs (id TEXT, code TEXT, language TEXT, parent_id TEXT, "
            "generation INTEGER, combined_score REAL, correct BOOLEAN)"
        )
        for program_id, source, parent_id, generation, score, correct in (
            ("root", "def solve():\n    return 0\n", None, 0, 0.0, 1),
            ("good", GOOD_SOURCE, "root", 7, 9999.0, 1),
            ("bad", BAD_SOURCE, "root", 8, 10000.0, 0),
        ):
            connection.execute(
                "INSERT INTO programs VALUES (?, ?, 'python', ?, ?, ?, ?)",
                (program_id, source, parent_id, generation, score, correct),
            )
            generation_root = native / f"gen_{generation}"
            generation_root.mkdir()
            (generation_root / "main.py").write_text(source, encoding="utf-8")

    generator = tmp_path / "generator.py"
    generator_calls = tmp_path / "generator-calls.jsonl"
    generator.write_text(
        "import json, pathlib, sys\n"
        "request = json.loads(pathlib.Path(sys.argv[1]).read_text())\n"
        f"with pathlib.Path({str(generator_calls)!r}).open('a') as stream:\n"
        "    stream.write(json.dumps({'iteration': request['iteration']}) + '\\n')\n"
        "print(json.dumps({'source': '# offspring\\ndef solve():\\n    return 1\\n'}))\n",
        encoding="utf-8",
    )
    evaluator = tmp_path / "evaluator.py"
    evaluator_calls = tmp_path / "evaluator-calls.jsonl"
    evaluator.write_text(
        "import json, pathlib, sys\n"
        "source = pathlib.Path(sys.argv[1]).read_text()\n"
        "label = source.splitlines()[0]\n"
        f"with pathlib.Path({str(evaluator_calls)!r}).open('a') as stream:\n"
        "    stream.write(json.dumps(label) + '\\n')\n"
        "valid = int(label != '# producer-bad')\n"
        "score = 0.42 if label == '# producer-good' else 0.1\n"
        "print(json.dumps({'schema_version': '1', 'evaluator_id': 'local-producer-fixture', "
        "'validity': valid, 'quality': score if valid else None, "
        "'combined_score': score if valid else 0, "
        "'detailed_scores': {'quality': {'value': score, 'direction': 'maximize'}}, "
        "'error_info': [] if valid else [{'code': 'invalid', 'message': 'fixture invalid'}]}))\n",
        encoding="utf-8",
    )
    return ProducerCase(
        root=tmp_path, contract=contract, native=native, exported=tmp_path / "exported",
        generator=generator, evaluator=evaluator,
        generator_calls=generator_calls, evaluator_calls=evaluator_calls,
    )


def _json_lines(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _tree_digests(path: Path) -> dict[str, str]:
    return {
        str(item.relative_to(path)): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in path.rglob("*") if item.is_file()
    }


def _export(case: ProducerCase, capsys, *, ids: tuple[str, ...] = ("good", "bad")) -> dict:
    arguments = [
        "export-shinka-result", str(case.native),
        "--output", str(case.exported),
        "--contract", str(case.contract),
        "--producer-fingerprint", PRODUCER_FINGERPRINT,
        "--producer-run-id", "offline-shinka-run",
        "--json",
    ]
    for program_id in ids:
        arguments.extend(("--program-id", program_id))
    before = _tree_digests(case.native)
    assert main(arguments) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["status"] == "exported"
    assert _tree_digests(case.native) == before
    assert not case.home.exists()
    assert not case.generator_calls.exists()
    assert not case.evaluator_calls.exists()
    return json.loads((case.exported / "producer-result.json").read_text(encoding="utf-8"))


def _start(case: ProducerCase, capsys) -> dict:
    assert main(case.evolve_arguments()) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def _seed_archive(case: ProducerCase) -> list[dict]:
    return [
        row for row in _json_lines(case.workspace / "evolution" / "archive.jsonl")
        if row["candidate_id"].startswith("seed-")
    ]


def test_shinka_cli_export_warms_population_with_local_score_and_invalid_subset(
    producer_case: ProducerCase, capsys,
) -> None:
    case = producer_case
    envelope = _export(case, capsys)
    assert len(envelope["materials"]) == 2
    assert [item["lineage"] for item in envelope["materials"]] == [["root"], ["root"]]
    exported_before = _tree_digests(case.exported)
    payload = _start(case, capsys)

    assert payload["best_score"] == 0.42
    assert payload["strategy"] == "population"
    seeds = _seed_archive(case)
    assert len(seeds) == 1
    seed = seeds[0]
    assert seed["candidate_id"] == payload["best_candidate_id"]
    assert seed["generation"] == seed["iteration"] == 0
    assert (case.workspace / seed["code_path"]).read_text(encoding="utf-8") == GOOD_SOURCE
    handoff = seed["metadata"]["seed_handoff"]
    assert handoff["lineage"] == ["root"]
    assert handoff["provenance"]["producer_id"] == "shinka"
    assert handoff["provenance"]["producer_run_id"] == "offline-shinka-run"
    seed_root = (case.workspace / seed["code_path"]).parent
    record = json.loads((seed_root / "record.json").read_text(encoding="utf-8"))
    evidence = record["seed_handoff_evidence"]["external_evidence"]
    assert set(evidence) == {"present", "score_present", "payload_sha256"}
    assert evidence["present"] is evidence["score_present"] is True
    receipt = seed_root / "receipt.json"
    assert receipt.is_file()

    events = Store(case.home / "state.db").list_events(payload["run_id"])
    adjudicated = [event for event in events if event["type"] == "seed_admission_adjudicated"]
    committed = [event for event in events if event["type"] == "seed_admission_committed"]
    assert len(adjudicated) == len(committed) == 1
    assert adjudicated[0]["payload"] == committed[0]["payload"]
    assert [item["code"] for item in adjudicated[0]["payload"]["rejected"]] == [
        "local_evaluation_invalid",
    ]
    canonical = json.dumps({"record": record, "receipt": json.loads(receipt.read_text())})
    assert "9999.0" not in canonical and "10000.0" not in canonical
    calls = _json_lines(case.evaluator_calls)
    assert calls.count("# producer-good") == calls.count("# producer-bad") == 1
    assert _json_lines(case.generator_calls) == [{"iteration": 1}]
    assert _tree_digests(case.exported) == exported_before


def test_producer_cli_resume_revalidates_seeds_without_replaying_generator(
    producer_case: ProducerCase, capsys,
) -> None:
    case = producer_case
    _export(case, capsys)
    first = _start(case, capsys)
    seeds = _seed_archive(case)
    evolution = case.workspace / "evolution"
    archive_before = (evolution / "archive.jsonl").read_bytes()
    state_before = json.loads((evolution / "state.json").read_text())
    events_before = [
        event for event in Store(case.home / "state.db").list_events(first["run_id"])
        if event["type"] in {"seed_admission_adjudicated", "seed_admission_committed"}
    ]
    generator_before = case.generator_calls.read_bytes()
    calls_before = _json_lines(case.evaluator_calls)
    assert main([*case.evolve_arguments(), "--resume", "--run-id", first["run_id"]]) == 0
    second = json.loads(capsys.readouterr().out)

    assert second["run_id"] == first["run_id"]
    assert second["best_candidate_id"] == first["best_candidate_id"]
    assert second["best_score"] == 0.42
    assert _seed_archive(case) == seeds
    assert (evolution / "archive.jsonl").read_bytes() == archive_before
    assert json.loads((evolution / "state.json").read_text())["seed_admission"] == (
        state_before["seed_admission"]
    )
    assert case.generator_calls.read_bytes() == generator_before
    fresh_calls = _json_lines(case.evaluator_calls)[len(calls_before):]
    assert fresh_calls.count("# producer-good") == fresh_calls.count("# producer-bad") == 1
    events_after = [
        event for event in Store(case.home / "state.db").list_events(first["run_id"])
        if event["type"] in {"seed_admission_adjudicated", "seed_admission_committed"}
    ]
    assert events_after == events_before


@pytest.mark.parametrize("resume", [False, True], ids=["fresh", "resume"])
@pytest.mark.parametrize("drift", ["source", "producer_fingerprint", "producer_id"])
def test_producer_cli_rejects_source_or_identity_drift_before_local_commands(
    producer_case: ProducerCase, capsys, drift: str, resume: bool,
) -> None:
    case = producer_case
    envelope = _export(case, capsys)
    initial = _start(case, capsys) if resume else None
    arguments = case.evolve_arguments()
    if initial is not None:
        arguments.extend(("--resume", "--run-id", initial["run_id"]))
    if drift == "source":
        material = case.exported / envelope["materials"][0]["path"]
        material.write_text(GOOD_SOURCE.replace("42", "43"), encoding="utf-8")
    else:
        option = "--producer-fingerprint" if drift == "producer_fingerprint" else "--producer-id"
        arguments[arguments.index(option) + 1] = "c" * 64 if drift == "producer_fingerprint" else "other"
    before = {
        path: path.read_bytes() if path.exists() else None
        for path in (case.generator_calls, case.evaluator_calls)
    }
    archive = case.workspace / "evolution" / "archive.jsonl"
    archive_before = archive.read_bytes() if archive.exists() else None
    assert main(arguments) == 2
    error = json.loads(capsys.readouterr().err)["error"]
    assert error == (
        "producer_material_digest_mismatch" if drift == "source" else "producer_identity_mismatch"
    )
    for path, content in before.items():
        assert (path.read_bytes() if path.exists() else None) == content
    assert (archive.read_bytes() if archive.exists() else None) == archive_before


def test_producer_cli_resume_rejects_changed_evaluator_command_before_execution(
    producer_case: ProducerCase, capsys,
) -> None:
    case = producer_case
    _export(case, capsys)
    first = _start(case, capsys)
    replacement = case.root / "other-evaluator.py"
    replacement.write_text(case.evaluator.read_text(), encoding="utf-8")
    arguments = case.evolve_arguments()
    arguments[arguments.index("--evaluator-command") + 1] = shlex.join(
        (sys.executable, str(replacement)),
    )
    before = (case.generator_calls.read_bytes(), case.evaluator_calls.read_bytes())
    archive = case.workspace / "evolution" / "archive.jsonl"
    archive_before = archive.read_bytes()
    assert main([*arguments, "--resume", "--run-id", first["run_id"]]) == 2
    error = json.loads(capsys.readouterr().err)["error"]
    assert "configuration does not match" in error
    assert (case.generator_calls.read_bytes(), case.evaluator_calls.read_bytes()) == before
    assert archive.read_bytes() == archive_before


def test_shinka_cli_all_invalid_material_does_not_start_population_search(
    producer_case: ProducerCase, capsys,
) -> None:
    case = producer_case
    _export(case, capsys, ids=("bad",))
    assert main(case.evolve_arguments()) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "no_usable_seeds"
    assert _json_lines(case.evaluator_calls) == ["# producer-bad"]
    assert not case.generator_calls.exists()
    archive = case.workspace / "evolution" / "archive.jsonl"
    assert not archive.exists() or archive.read_bytes() == b""
    store = Store(case.home / "state.db")
    run = store.get_run_by_workspace(case.workspace)
    assert run is not None
    events = store.list_events(run.id)
    failure = next(event for event in events if event["type"] == "seed_admission_failed")
    assert [item["code"] for item in failure["payload"]["rejected"]] == [
        "local_evaluation_invalid",
    ]
    assert not any(event["type"] == "seed_admission_committed" for event in events)


@pytest.mark.parametrize("field", ["budget", "producer_run_id"])
def test_producer_cli_resume_refuses_changed_envelope_with_unchanged_sources(
    producer_case: ProducerCase, capsys, field: str,
) -> None:
    case = producer_case
    envelope = _export(case, capsys)
    first = _start(case, capsys)
    envelope[field] = {"top_k": 3} if field == "budget" else "different-native-run"
    (case.exported / "producer-result.json").write_text(
        json.dumps(envelope, sort_keys=True, indent=2) + "\n", encoding="utf-8",
    )
    generator_before = case.generator_calls.read_bytes()
    archive = case.workspace / "evolution" / "archive.jsonl"
    archive_before = archive.read_bytes()
    assert main([*case.evolve_arguments(), "--resume", "--run-id", first["run_id"]]) == 2
    error = json.loads(capsys.readouterr().err)["error"]
    assert isinstance(error, str) and error
    assert case.generator_calls.read_bytes() == generator_before
    assert archive.read_bytes() == archive_before
