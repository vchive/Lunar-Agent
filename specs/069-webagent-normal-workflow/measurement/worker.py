"""One registered slot through the existing EffectTrialRunner, without retry or score shortcuts.

Importing this module is offline. Only main() reads the environment, and only the guarded process
executor dispatches a subject or exact harness. Provider values never enter diagnostic artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import time
from pathlib import Path
from typing import Any

from famou.effect_adapters import famou_case_content_digest
from famou.effect_trial import (
    EffectTrialConfig,
    EffectTrialError,
    EffectTrialRunner,
    TrialBaseline,
    TrialSuite,
    _canonical_bytes,
    _default_executor,
    _profile_digest,
)
from famou.profiles import ModelProfile
from famou.staged_workflow import StagedWorkflowConfig, StagePolicy

REPO = Path(__file__).absolute().parents[3]
HARNESS_PYTHON = ".lunar/harness-venv-high-score-20260909/bin/python"
SUBJECT_ENV_NAMES = ("FAMOU_MODEL_ENDPOINT", "FAMOU_API_KEY")
HARNESS_ENV_NAMES = ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL")
MAX_JSON_BYTES = 2 * 1024 * 1024


def require(condition: object) -> None:
    if not condition:
        raise EffectTrialError("measurement_binding_failed")


def confined(root: Path, relative: str) -> Path:
    """Confine control/source paths and reject existing symlink ancestors."""
    path = Path(relative)
    require(bool(relative) and not path.is_absolute() and "\\" not in relative)
    require(path.as_posix() == relative and all(part not in {"", ".", ".."} for part in path.parts))
    require(root.is_absolute() and root.resolve() == root and not root.is_symlink())
    current = root
    for part in path.parts:
        current = current / part
        require(not current.is_symlink())
    require(current.resolve(strict=False).is_relative_to(root))
    return current


def read_json(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink())
    with path.open("rb") as stream:
        content = stream.read(MAX_JSON_BYTES + 1)
    require(0 < len(content) <= MAX_JSON_BYTES)
    value = json.loads(content)
    require(isinstance(value, dict))
    return value


def file_sha256(path: Path) -> str:
    require(path.is_file() and not path.is_symlink())
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def expected_request(suite: dict[str, Any], profile_sha256: str) -> dict[str, object]:
    parsed = TrialSuite.from_dict(suite)
    require(len(parsed.cases) == 1)
    case = parsed.cases[0]
    return {
        "schema_version": "1", "mode": "normal", "benchmark": parsed.benchmark.to_dict(),
        "case": case.public_identity(), "run_index": 1, "requested_model": "glm-5.2",
        "model_profile_sha256": profile_sha256, "entrypoint": case.entrypoint,
        "public_files": [item.to_dict() for item in case.public_files], "receipt_path": "receipt.json",
    }


def request_sha256(suite: dict[str, Any], profile_sha256: str) -> str:
    # Native trial requests use a trailing newline; profile/source digests do not.
    return hashlib.sha256(_canonical_bytes(expected_request(suite, profile_sha256))).hexdigest()


def write_new(path: Path, payload: dict[str, Any]) -> None:
    require(path.parent.is_dir() and path.parent.resolve() == path.parent)
    content = _canonical_bytes(payload)
    require(len(content) <= MAX_JSON_BYTES)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def load_registration(manifest_path: Path) -> tuple[dict[str, Any], str]:
    require(manifest_path.is_absolute())
    path = confined(REPO, manifest_path.relative_to(REPO).as_posix())
    digest = file_sha256(path)
    anchor = path.with_suffix(".sha256")
    require(anchor.is_file() and not anchor.is_symlink() and anchor.stat().st_size <= 128)
    require(anchor.read_text().strip() == digest)
    return read_json(path), digest


def select_slot(manifest: dict[str, Any], index: int) -> dict[str, Any]:
    require(type(index) is int and index in (1, 2, 3, 4))
    slots = manifest["slots"]
    require(isinstance(slots, list) and [slot["index"] for slot in slots] == [1, 2, 3, 4])
    slot = slots[index - 1]
    require(slot["arm"] in {"M", "S"})
    return slot


def input_path(campaign: Path, name: str) -> Path:
    return confined(campaign, "inputs/" + name)


def verify_bindings(
    manifest_path: Path, campaign: Path, manifest: dict[str, Any], manifest_sha: str,
    slot: dict[str, Any], *, require_started: bool = True,
) -> None:
    """Read-only recheck used immediately before every subject/harness process."""
    loaded, actual_manifest_sha = load_registration(manifest_path)
    require(loaded == manifest and actual_manifest_sha == manifest_sha)
    require(campaign.name == manifest["campaign_id"])
    require(confined(REPO, campaign.relative_to(REPO).as_posix()) == campaign)
    require(select_slot(manifest, slot["index"]) == slot)
    require(manifest["execution"]["waves"] == [[1, 2], [3, 4]])
    for field, expected in (
        ("subject_outer_seconds", 5430), ("harness_outer_seconds", 3630),
        ("slot_outer_seconds", 9300),
    ):
        require(manifest["execution"][field] == expected)
    sources = manifest["source_files_sha256"]
    require(isinstance(sources, dict) and bool(sources))
    actual_sources = {
        path.relative_to(REPO).as_posix(): file_sha256(
            confined(REPO, path.relative_to(REPO).as_posix())
        )
        for path in sorted((REPO / "src/famou").rglob("*.py"))
    }
    require(actual_sources == sources and canonical_sha256(sources) == manifest["source_sha256"])
    for relative, expected in manifest["frozen_files_sha256"].items():
        require(file_sha256(confined(REPO, relative)) == expected)
    require(Path(__file__).relative_to(REPO).as_posix() in manifest["frozen_files_sha256"])
    require(HARNESS_PYTHON in manifest["frozen_files_sha256"])
    case_key = slot["case_key"]
    case_info = manifest["cases"][case_key]
    suite = read_json(input_path(campaign, case_key + "-suite.json"))
    require(suite == case_info["suite"])
    parsed = TrialSuite.from_dict(suite)
    require(len(parsed.cases) == 1 and parsed.cases[0].key == case_key)
    profile = ModelProfile.from_dict(read_json(input_path(campaign, "profile.json")))
    require(profile.to_dict() == manifest["profile"])
    require(_profile_digest(profile) == manifest["profile_sha256"])
    require(profile.model == "glm-5.2" and profile.max_steps == 200)
    require(profile.timeout_seconds == 5400 and profile.max_total_tokens == 8000000)
    require(profile.thinking_budget == 0 and profile.max_cost_micros is None)
    require(profile.input_cost_per_1k_micros is None and profile.output_cost_per_1k_micros is None)
    require(slot["request_sha256"] == request_sha256(suite, manifest["profile_sha256"]))
    baseline = TrialBaseline.from_dict(read_json(input_path(campaign, case_key + "-baseline.json")))
    require(baseline.source == "company-platform" and baseline.conclusion_eligibility == "ineligible")
    require(baseline.provenance is not None and baseline.provenance.adapter == "agentserver")
    private = confined(REPO, case_info["private_root_rel"])
    require(famou_case_content_digest(private) == parsed.cases[0].digest)
    for name, expected in (
        ("extractor_agent.py", parsed.cases[0].harness.extractor_sha256),
        ("evaluator.py", parsed.cases[0].harness.evaluator_sha256),
    ):
        require(file_sha256(confined(private, "tests/" + name)) == expected)
    required_inputs = ["profile.json", case_key + "-suite.json", case_key + "-baseline.json"]
    StagePolicy.from_dict(manifest["policy"])
    if slot["arm"] == "S":
        name = f"slot-{slot['index']:03d}-workflow.json"
        required_inputs.append(name)
        workflow = StagedWorkflowConfig.load(input_path(campaign, name))
        require(workflow.to_dict() == slot["workflow_config"])
        require(workflow.policy == StagePolicy.from_dict(manifest["policy"]))
        control = workflow.manifest
        require(control.run_id == f"{manifest['campaign_id']}-slot-{slot['index']:03d}")
        require(control.attempt_id == f"slot-{slot['index']:03d}-attempt-001")
        require(control.source_sha256 == manifest["source_sha256"])
        require(control.request_sha256 == slot["request_sha256"])
        require(control.model_profile_sha256 == manifest["profile_sha256"])
        require(control.suite_key == parsed.benchmark.name and control.case_key == case_key)
        require(dict(control.ceilings) == {
            "max_wall_seconds": 5400, "max_tool_steps": 200,
            "max_total_tokens": 8000000, "max_cost_micros": None,
        })
    else:
        require(slot["workflow_config"] is None)
    for name in required_inputs:
        require(input_path(campaign, name).relative_to(REPO).as_posix() in manifest["frozen_files_sha256"])
    if require_started:
        for name in ("started.json", f"slot-{slot['index']:03d}-started.json"):
            marker = read_json(confined(campaign, name))
            require(marker["manifest_sha256"] == manifest_sha)
            if name != "started.json":
                require(marker["index"] == slot["index"])
        require(not os.path.lexists(campaign / "terminated.json"))
        require(not os.path.lexists(campaign / f"slot-{slot['index']:03d}-terminated.json"))


def split_environment(configured: dict[str, str], manifest: dict[str, Any]) -> tuple[dict, dict]:
    for name in (*SUBJECT_ENV_NAMES, *HARNESS_ENV_NAMES):
        require(isinstance(configured.get(name), str) and bool(configured[name]))
    require(configured["ANTHROPIC_MODEL"] == "glm-5.2")
    for name in ("FAMOU_MODEL_ENDPOINT", "ANTHROPIC_BASE_URL"):
        require(hashlib.sha256(configured[name].encode()).hexdigest() == manifest["endpoints"][name])
    extra = {"PYTHONDONTWRITEBYTECODE": "1"}
    return (
        {**extra, **{name: configured[name] for name in SUBJECT_ENV_NAMES}},
        {**extra, **{name: configured[name] for name in HARNESS_ENV_NAMES}},
    )


def commands(manifest: dict[str, Any], campaign: Path, slot: dict[str, Any]) -> tuple[tuple, tuple]:
    """Frozen command shape, with request and model profile appended by the native runner."""
    cli = str(REPO / ".venv/bin/lunar-agent")
    subject = (cli, "effect-subject", "--model", "glm-5.2", "--max-steps", "200",
               "--timeout", "5400", "--json")
    if slot["arm"] == "S":
        subject += ("--workflow-config", str(input_path(campaign, f"slot-{slot['index']:03d}-workflow.json")))
    case_key = slot["case_key"]
    case = manifest["cases"][case_key]
    harness = (
        cli, "effect-harness", "--case-root", str(confined(REPO, case["private_root_rel"])),
        "--python", str(REPO / HARNESS_PYTHON), "--timeout", "1800", "--json",
        "--extractor-env", "ANTHROPIC_BASE_URL", "--extractor-env", "ANTHROPIC_AUTH_TOKEN",
        "--extractor-env", "ANTHROPIC_MODEL",
    )
    return subject, harness


def build_runner(
    manifest: dict[str, Any], campaign: Path, slot: dict[str, Any],
    configured: dict[str, str], *, process_executor,
) -> EffectTrialRunner:
    """Construct the unchanged native runner; no dispatch occurs here."""
    subject_env, harness_env = split_environment(configured, manifest)
    subject, harness = commands(manifest, campaign, slot)
    case_key = slot["case_key"]
    case = manifest["cases"][case_key]
    config = EffectTrialConfig(
        runs_per_case=1, timeout_seconds=5400, requested_model="glm-5.2",
        subject_command=subject, harness_command=harness,
        subject_environment=subject_env, harness_environment=harness_env,
        model_profile_sha256=manifest["profile_sha256"],
        subject_model_profile_path=input_path(campaign, "profile.json"),
    )
    return EffectTrialRunner(
        input_path(campaign, case_key + "-suite.json"),
        input_path(campaign, case_key + "-baseline.json"),
        confined(campaign, f"slots/{slot['index']:03d}/trial"),
        case_sources={case_key: confined(REPO, case["public_root_rel"])}, config=config,
        process_executor=process_executor,
    )


class RegisteredExecutor:
    """Adds identity checks and process-only evidence around the native bounded executor."""

    def __init__(self, manifest_path: Path, campaign: Path, manifest: dict, manifest_sha: str, slot: dict):
        self.manifest_path, self.campaign = manifest_path, campaign
        self.manifest, self.manifest_sha, self.slot = manifest, manifest_sha, slot
        self.slot_root = confined(campaign, f"slots/{slot['index']:03d}")
        self.called: list[str] = []

    def __call__(self, command, *, cwd: Path, env, timeout):
        phase = command[1]
        require(phase in {"effect-subject", "effect-harness"})
        stage = "subject" if phase == "effect-subject" else "harness"
        require(stage not in self.called and (stage == "subject" or self.called == ["subject"]))
        require(timeout == 5400)
        verify_bindings(self.manifest_path, self.campaign, self.manifest, self.manifest_sha, self.slot)
        expected_cwd = confined(
            self.slot_root,
            f"trial/cases/{self.slot['case_key']}/runs/001/attempts/001/{stage}",
        )
        require(cwd == expected_cwd and Path(command[-1]) == cwd / "request.json")
        subject_command, harness_command = commands(self.manifest, self.campaign, self.slot)
        expected_command = (
            (*subject_command, "--model-profile", str(input_path(self.campaign, "profile.json")))
            if stage == "subject" else harness_command
        )
        require(tuple(command) == (*expected_command, str(cwd / "request.json")))
        if stage == "subject":
            require(file_sha256(cwd / "request.json") == self.slot["request_sha256"])
        allowed = set(SUBJECT_ENV_NAMES if stage == "subject" else HARNESS_ENV_NAMES)
        allowed |= {"PATH", "LANG", "LC_ALL", "PYTHONUTF8", "PYTHONDONTWRITEBYTECODE"}
        require(set(env) == allowed)
        self.called.append(stage)
        outer = self.manifest["execution"][stage + "_outer_seconds"]
        event = {
            "schema_version": "1", "index": self.slot["index"], "stage": stage,
            "manifest_sha256": self.manifest_sha, "started_unix_seconds": time.time(),
            "worker_pid": os.getpid(), "worker_pgid": os.getpgrp(),
            "child_pid": None, "child_pgid": None, "process_ids_observed": False,
            "outer_timeout_seconds": outer, "request_sha256": file_sha256(cwd / "request.json"),
        }
        write_new(self.slot_root / f"{stage}-started.json", event)
        started = time.monotonic()
        returncode, error_type = None, None
        try:
            result = _default_executor(command, cwd=cwd, env=env, timeout=outer)
            returncode = result.returncode
            return result
        except BaseException as exc:
            error_type = type(exc).__name__
            raise
        finally:
            write_new(self.slot_root / f"{stage}-terminated.json", {
                "schema_version": "1", "index": self.slot["index"], "stage": stage,
                "manifest_sha256": self.manifest_sha, "returncode": returncode,
                "error_type": error_type, "elapsed_seconds": round(time.monotonic() - started, 3),
            })


def install_termination_handler() -> None:
    def terminate(_signum, _frame):
        # Native _default_executor catches BaseException and kills its separate child group.
        raise SystemExit(124)

    signal.signal(signal.SIGTERM, terminate)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--slot", required=True, type=int)
    args = parser.parse_args()
    manifest_path, campaign = args.manifest.absolute(), args.campaign.absolute()
    manifest, manifest_sha = load_registration(manifest_path)
    slot = select_slot(manifest, args.slot)
    slot_root = confined(campaign, f"slots/{args.slot:03d}")
    require(campaign.name == manifest["campaign_id"])
    require(not os.path.lexists(slot_root / "trial"))
    require(not os.path.lexists(slot_root / "outcome.json"))
    slot_root.mkdir(parents=True, exist_ok=True)
    write_new(slot_root / "worker-started.json", {
        "schema_version": "1", "index": args.slot, "manifest_sha256": manifest_sha,
        "pid": os.getpid(), "pgid": os.getpgrp(), "started_unix_seconds": time.time(),
    })
    install_termination_handler()
    started = time.monotonic()
    outcome = {
        "schema_version": "1", "index": args.slot, "arm": slot["arm"], "case_key": slot["case_key"],
        "manifest_sha256": manifest_sha, "status": "failed", "error_type": None,
        "record_sha256": None, "report_sha256": None,
    }
    returncode = 2
    try:
        verify_bindings(manifest_path, campaign, manifest, manifest_sha, slot)
        configured = {name: os.environ[name] for name in (*SUBJECT_ENV_NAMES, *HARNESS_ENV_NAMES)}
        executor = RegisteredExecutor(manifest_path, campaign, manifest, manifest_sha, slot)
        runner = build_runner(manifest, campaign, slot, configured, process_executor=executor)
        report = runner.run().to_dict()
        record_path = confined(slot_root, f"trial/cases/{slot['case_key']}/runs/001/record.json")
        record = read_json(record_path)
        record_sha = hashlib.sha256(_canonical_bytes(record)).hexdigest()
        state = read_json(confined(slot_root, "trial/control/state.json"))
        require(state["records"] == {slot["case_key"] + "/001": record_sha})
        require(len(report["cases"]) == 1 and len(report["cases"][0]["runs"]) == 1)
        outcome.update({
            "status": "terminated", "record_status": record["status"], "record_sha256": record_sha,
            "report_sha256": file_sha256(confined(slot_root, "trial/report.json")),
        })
        returncode = 0
    except BaseException as exc:  # noqa: BLE001 - bounded redacted outcome after SIGTERM cleanup
        outcome["error_type"] = type(exc).__name__
        if isinstance(exc, SystemExit):
            returncode = 124
    finally:
        outcome["elapsed_seconds"] = round(time.monotonic() - started, 3)
        outcome["worker_returncode"] = returncode
        write_new(slot_root / "outcome.json", outcome)
        write_new(slot_root / "worker-terminated.json", {
            "schema_version": "1", "index": args.slot, "manifest_sha256": manifest_sha,
            "returncode": returncode, "outcome_sha256": file_sha256(slot_root / "outcome.json"),
        })
    print(json.dumps({"index": args.slot, "status": outcome["status"], "error_type": outcome["error_type"]}), flush=True)
    return returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - never print provider-bearing exception details
        print(json.dumps({"status": "worker_rejected", "error_type": type(exc).__name__}), flush=True)
        raise SystemExit(2) from None
