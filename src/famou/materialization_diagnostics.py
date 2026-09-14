"""Bounded observations of retained materialization evidence, never recovery authority."""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import stat
from contextlib import ExitStack
from pathlib import Path

from .diagnostic_snapshot import DiagnosticSnapshotError, diagnostic_snapshot
from .evolution import CandidateExecution, EvolutionError, _strict_json_loads

STAGES = ("launch", "execution", "delivery", "outputs", "terminal")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_ATTEMPT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}-[0-9a-f]{12}")
_BASE = "evolution/materialization"
_NEXT = {
    "observed": "Use normal resume for authorization and acceptance checks; this report does not establish recovery eligibility.",
    "attention_required": "Preserve the database and run files. Review the reported evidence before normal resume; do not remove or reconstruct records based on this report.",
    "busy": "An inspection lock is busy. Retry after the active operation settles; no process was identified or stopped.",
    "unavailable": "Preserve the evidence. Check the run IDs and storage, then retry when the source is stable and readable.",
}
_EVENTS = {
    "launch": {"materialization_launch_intended": "event-materialization-launch-intended-"},
    "execution": {
        "materialization_execution_prepared": "event-materialization-execution-prepared-",
        "materialization_execution_committed": "event-materialization-execution-committed-",
        "evolved_candidate_executed": None,
    },
    "delivery": {"materialization_delivery_prepared": "event-materialization-delivery-prepared-"},
    "outputs": {
        "evolved_outputs_promoted": "event-evolved-outputs-promoted-",
        "output_publication_committed": "event-output-publication-committed-",
    },
    "terminal": {
        "materialization_publication_prepared": "event-materialization-publication-prepared-",
        "materialization_publication_committed": "event-materialization-publication-committed-",
        "evolved_candidate_materialized": "event-evolved-materialization-",
    },
}
_RESULT_KEYS = {
    "schema_version", "status", "parent_run_id", "evolution_run_id", "contract_sha256",
    "candidate_id", "candidate_path", "candidate_sha256", "attempt_path", "execution",
    "validation", "outputs", "error",
}
_SHAPES = {
    ("launch", "intent"): {
        "schema_version", "parent_run_id", "evolution_run_id", "task_id", "contract_sha256",
        "strategy", "candidate_id", "candidate_path", "candidate_sha256", "attempt_path",
        "runner_sha256", "timeout_seconds",
    },
    ("execution", "journal"): {
        "schema_version", "parent_run_id", "evolution_run_id", "task_id", "launch_intent_sha256",
        "execution_path", "execution_sha256", "execution_size", "artifact_id", "device", "inode",
    },
    ("delivery", "plan"): {
        "schema_version", "parent_run_id", "evolution_run_id", "task_id", "launch_intent_sha256",
        "execution_journal_sha256", "execution_sha256", "result", "outputs",
    },
    ("outputs", "journal"): {"schema_version", "parent_run_id", "evolution_run_id", "owner_task_id", "entries"},
    ("terminal", "journal"): {
        "schema_version", "parent_run_id", "evolution_run_id", "task_id", "marker_path",
        "marker_sha256", "marker_size", "artifact_id", "device", "inode",
    },
    ("terminal", "result_blob"): _RESULT_KEYS,
    ("terminal", "marker"): _RESULT_KEYS,
}


class _Unavailable(Exception):
    pass


def _stamp(info: os.stat_result) -> tuple:
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


class _Reader:
    def __init__(self):
        self.observed: dict[Path, tuple | None] = {}

    def info(self, path: Path):
        """Observe every ancestor without following symlinks, including absent ancestors."""
        parts = path.parts
        current = Path(path.anchor)
        for index, part in enumerate(parts[1:]):
            current /= part
            try:
                info = os.lstat(current)
            except FileNotFoundError:
                self.observed.setdefault(current, None)
                return None
            value = _stamp(info)
            previous = self.observed.get(current)
            if current in self.observed and (previous is None or previous != value[:len(previous)]):
                raise _Unavailable("diagnostic_files_changed")
            # Ancestor entry churn outside the workspace is irrelevant (including
            # our private temporary DB copies); still detect ancestor replacement.
            if index == len(parts) - 2 or (previous is not None and len(previous) > 3):
                self.observed[current] = value
            else:
                self.observed[current] = value[:3]
            if stat.S_ISLNK(info.st_mode) or (index < len(parts) - 2 and not stat.S_ISDIR(info.st_mode)):
                raise _Unavailable("diagnostic_path_unsafe")
        return info

    def verify(self):
        for path, expected in self.observed.items():
            try:
                current = _stamp(os.lstat(path))
            except FileNotFoundError:
                current = None
            if current is not None and expected is not None:
                current = current[:len(expected)]
            if current != expected:
                raise _Unavailable("diagnostic_files_changed")

    def node(self, path: Path, *, directory=False, limit=64 * 1024):
        try:
            info = self.info(path)
            if info is None:
                return {"state": "absent"}, None
            if directory:
                return {"state": "present" if stat.S_ISDIR(info.st_mode) else "unsafe"}, None
            if not stat.S_ISREG(info.st_mode):
                return {"state": "unsafe"}, None
            if info.st_size > limit:
                return {"state": "invalid", "issue": "record_size_limit"}, None
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            try:
                if _stamp(os.fstat(descriptor)) != _stamp(info):
                    raise _Unavailable("diagnostic_files_changed")
                chunks, size = [], 0
                while size <= limit:
                    chunk = os.read(descriptor, min(65536, limit + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                if _stamp(os.fstat(descriptor)) != _stamp(info):
                    raise _Unavailable("diagnostic_files_changed")
            finally:
                os.close(descriptor)
            content = b"".join(chunks)
            if len(content) > limit:
                return {"state": "invalid", "issue": "record_size_limit"}, None
            observed = {"state": "present", "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            try:
                value = _strict_json_loads(content)
                if not isinstance(value, dict):
                    raise TypeError
                # A report inspects the record envelope, not candidate acceptance.
                return observed, value
            except (EvolutionError, ValueError, TypeError, RecursionError):
                return {**observed, "state": "invalid", "issue": "record_json_invalid"}, None
        except _Unavailable as exc:
            if str(exc) == "diagnostic_files_changed":
                raise
            return {"state": "unsafe"}, None
        except OSError:
            return {"state": "unavailable"}, None

    def lock(self, path: Path, stack: ExitStack):
        info = self.info(path)
        if info is None:
            return {"state": "absent"}
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise _Unavailable("diagnostic_lock_unsafe")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        stack.callback(os.close, descriptor)
        if _stamp(os.fstat(descriptor)) != _stamp(info):
            raise _Unavailable("diagnostic_files_changed")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            raise _Unavailable("diagnostic_lock_busy") from None
        return {"state": "present"}


def _stage():
    return {"state": "absent", "files": {}, "events": {}, "artifacts": 0, "issues": []}


def _issue(stage, code):
    if code not in stage["issues"]:
        stage["issues"].append(code)


def _path(raw: str) -> Path:
    if not isinstance(raw, str) or not raw or "\0" in raw or len(raw) > 4096 or not Path(raw).is_absolute():
        raise _Unavailable("diagnostic_workspace_unsafe")
    if len(Path(raw).parts) < 2 or any(part == ".." for part in Path(raw).parts):
        raise _Unavailable("diagnostic_workspace_unsafe")
    return Path(raw)


def _read_files(reader, stages, roots, suffix):
    parent, child = roots
    materialization = child / _BASE
    directories = {
        "launch": materialization,
        "execution": materialization / ".execution-publication",
        "delivery": materialization / ".delivery-publication",
        "outputs": parent / ".evolved-output-publications" / suffix,
        "terminal": materialization / ".terminal-publication",
    }
    names = {
        "launch": {"intent": "launch-intent.json", "temporary_intent": ".launch-intent.json.tmp"},
        "execution": {"journal": "journal.json", "temporary_journal": ".journal.json.tmp", "completed": "completed.json", "temporary_completed": ".completed.json.tmp"},
        "delivery": {"plan": "plan.json", "temporary_plan": ".plan.json.tmp", "completed": "completed.json", "temporary_completed": ".completed.json.tmp"},
        "outputs": {"journal": "journal.json", "temporary_journal": ".journal.json.tmp", "rolled_back": "rolled-back.json", "temporary_rolled_back": ".rolled-back.json.tmp"},
        "terminal": {"journal": "journal.json", "temporary_journal": ".journal.json.tmp", "result_blob": "result.blob", "completed": "completed.json", "temporary_completed": ".completed.json.tmp"},
    }
    values = {}

    def read(stage, key, path):
        limit = 128 * 1024 if stage == "outputs" else 64 * 1024
        if key in {"completed", "temporary_completed", "rolled_back", "temporary_rolled_back"} or (
            key in {"journal", "temporary_journal"} and stage != "outputs"
        ):
            limit = 4096
        if stage == "launch":
            limit = 8192
        observation, value = reader.node(path, limit=limit)
        stages[stage]["files"][key] = observation
        values[stage, key] = value

    for stage, directory in directories.items():
        stages[stage]["files"]["directory"] = reader.node(directory, directory=True)[0]
        for key, name in names[stage].items():
            read(stage, key, directory / name)
    read("terminal", "marker", materialization / "result.json")
    read("terminal", "temporary_marker", materialization / ".result.json.tmp")
    # Scan only immediate, bounded attempt directories; never follow a path taken from JSON.
    attempts = []
    if stages["launch"]["files"]["directory"]["state"] == "present":
        with os.scandir(materialization) as entries:
            for index, entry in enumerate(entries):
                if index >= 64:
                    raise _Unavailable("diagnostic_attempt_limit")
                if _ATTEMPT.fullmatch(entry.name):
                    attempts.append(entry.name)
    if len(attempts) == 1:
        read("execution", "attempt_execution", materialization / attempts[0] / "execution.json")
        read("execution", "temporary_execution", materialization / attempts[0] / ".execution.json.tmp")
        for stage, key, field, expected in (
            ("launch", "intent", "attempt_path", _BASE + "/" + attempts[0]),
            ("execution", "journal", "execution_path", _BASE + "/" + attempts[0] + "/execution.json"),
            ("terminal", "marker", "attempt_path", _BASE + "/" + attempts[0]),
            ("terminal", "result_blob", "attempt_path", _BASE + "/" + attempts[0]),
        ):
            value = values.get((stage, key))
            if value is not None and value.get(field) != expected:
                _issue(stages[stage], "attempt_identity_mismatch")
    else:
        state = "absent" if not attempts else "unavailable"
        for key in ("attempt_execution", "temporary_execution"):
            stages["execution"]["files"][key] = {"state": state}
        if attempts:
            _issue(stages["execution"], "multiple_attempt_directories")
    return values


def _ledger(snapshot, stages, parent, child, suffix):
    matched = {}
    for stage, types in _EVENTS.items():
        for kind, prefix in types.items():
            expected_run = parent if stage == "outputs" or kind == "evolved_candidate_materialized" else child
            reserved = prefix + suffix if prefix else None
            rows = [event for event in snapshot["events"] if (reserved is not None and event["id"] == reserved) or (
                event["type"] == kind and event["run_id"] == expected_run
                and (expected_run == child or event["payload"].get("evolution_run_id") == child)
            )]
            stages[stage]["events"][kind] = len(rows)
            matched[kind] = rows
            if len(rows) > 1:
                _issue(stages[stage], "duplicate_receipt")
            for row in rows:
                payload = row["payload"]
                if row["type"] != kind or row["run_id"] != expected_run:
                    _issue(stages[stage], "receipt_identity_mismatch")
                if any(payload.get(key) != value for key, value in (
                    ("parent_run_id", parent), ("evolution_run_id", child),
                ) if key in payload):
                    _issue(stages[stage], "receipt_identity_mismatch")
                if reserved is not None and row["id"] != reserved:
                    _issue(stages[stage], "receipt_identity_mismatch")
    for artifact in snapshot["artifacts"]:
        path = artifact["path"]
        if artifact["id"] == "artifact-materialization-execution-" + suffix or (
            artifact["run_id"] == child and isinstance(path, str) and path.startswith(_BASE + "/") and path.endswith("/execution.json")
        ):
            stages["execution"]["artifacts"] += 1
        elif artifact["id"] == "artifact-materialization-publication-" + suffix or (
            artifact["run_id"] == child and path == _BASE + "/result.json"
        ):
            stages["terminal"]["artifacts"] += 1
        elif isinstance(path, str) and artifact["id"] == "artifact-output-publication-" + hashlib.sha256(
            f"{parent}\0{child}\0{path}".encode()
        ).hexdigest():
            stages["outputs"]["artifacts"] += 1
    return matched


def _assess(stages, values, matched, parent, child, task_id):
    for (stage, key), value in values.items():
        if value is None:
            continue
        base_key = key.removeprefix("temporary_")
        shape = _SHAPES.get((stage, base_key))
        if shape is not None and (set(value) != shape or value.get("schema_version") != "1"):
            _issue(stages[stage], "record_shape_mismatch")
        if any(not isinstance(item, str) or re.fullmatch(r"[0-9a-f]{64}", item) is None
               for field, item in value.items() if field.endswith("sha256")):
            _issue(stages[stage], "record_shape_mismatch")
        if stage == "execution" and key in {"attempt_execution", "temporary_execution"}:
            try:
                if CandidateExecution.from_dict(value).to_dict() != value:
                    _issue(stages[stage], "record_shape_mismatch")
            except (EvolutionError, ValueError, TypeError):
                _issue(stages[stage], "record_shape_mismatch")
        for field, expected in (("parent_run_id", parent), ("evolution_run_id", child), ("task_id", task_id)):
            if field in value and value[field] != expected:
                _issue(stages[stage], "record_identity_mismatch")
        if key.startswith("temporary_"):
            final = stages[stage]["files"].get(base_key)
            if final and final["state"] == "present":
                if final.get("sha256") != stages[stage]["files"][key].get("sha256"):
                    _issue(stages[stage], "temporary_record_mismatch")
            else:
                _issue(stages[stage], "temporary_record_only")

    bindings = (
        ("launch", "intent", "materialization_launch_intended", "intent_sha256"),
        ("execution", "journal", "materialization_execution_prepared", "journal_sha256"),
        ("execution", "journal", "materialization_execution_committed", "journal_sha256"),
        ("delivery", "plan", "materialization_delivery_prepared", "plan_sha256"),
        ("outputs", "journal", "output_publication_committed", "journal_sha256"),
        ("terminal", "journal", "materialization_publication_prepared", "journal_sha256"),
        ("terminal", "journal", "materialization_publication_committed", "journal_sha256"),
    )
    for stage, key, kind, field in bindings:
        file = stages[stage]["files"][key]
        rows = matched[kind]
        for row in rows:
            if file["state"] == "absent":
                _issue(stages[stage], "receipt_without_record")
            elif file["state"] == "present" and row["payload"].get(field) != file.get("sha256"):
                _issue(stages[stage], "receipt_digest_mismatch")
            if row["run_id"] == child and (row["task_id"] != task_id or (
                stage != "launch" and row["payload"].get("owner_task_id") != task_id
            )):
                _issue(stages[stage], "receipt_identity_mismatch")

    primary = {"launch": ("intent", "materialization_launch_intended"),
               "execution": ("journal", "materialization_execution_prepared"),
               "delivery": ("plan", "materialization_delivery_prepared"),
               "outputs": ("journal", "output_publication_committed"),
               "terminal": ("journal", "materialization_publication_prepared")}
    for stage, (file, kind) in primary.items():
        if stages[stage]["files"][file]["state"] == "present" and not matched[kind]:
            _issue(stages[stage], "record_without_receipt")

    for stage, committed in (("execution", "materialization_execution_committed"),
                             ("terminal", "materialization_publication_committed")):
        if stages[stage]["files"]["journal"]["state"] == "present":
            if not matched[committed]:
                _issue(stages[stage], "registration_not_observed")
            elif not stages[stage]["artifacts"]:
                _issue(stages[stage], "registration_artifact_missing")
            if stages[stage]["files"]["completed"]["state"] == "absent":
                _issue(stages[stage], "completion_not_observed")
    if stages["delivery"]["files"]["plan"]["state"] == "present" and stages["delivery"]["files"]["completed"]["state"] == "absent":
        _issue(stages["delivery"], "completion_not_observed")
    for stage, key in (("execution", "attempt_execution"), ("terminal", "marker")):
        if stages[stage]["files"][key]["state"] == "present" and stages[stage]["files"]["journal"]["state"] == "absent":
            _issue(stages[stage], "legacy_or_unprepared_evidence")

    for stage, key, target_stage, target_key, digest_key, size_key in (
        ("execution", "journal", "execution", "attempt_execution", "execution_sha256", "execution_size"),
        ("terminal", "journal", "terminal", "result_blob", "marker_sha256", "marker_size"),
        ("delivery", "plan", "execution", "journal", "execution_journal_sha256", None),
        ("delivery", "plan", "execution", "attempt_execution", "execution_sha256", None),
        ("delivery", "plan", "launch", "intent", "launch_intent_sha256", None),
        ("execution", "journal", "launch", "intent", "launch_intent_sha256", None),
    ):
        value = values.get((stage, key))
        target = stages[target_stage]["files"][target_key]
        if value is not None and (value.get(digest_key) != target.get("sha256") or (
            size_key and (type(value.get(size_key)) is not int or value[size_key] != target.get("size"))
        )):
            _issue(stages[stage], "record_digest_mismatch")
    marker, blob = (stages["terminal"]["files"][key] for key in ("marker", "result_blob"))
    if marker["state"] == blob["state"] == "present" and marker["sha256"] != blob["sha256"]:
        _issue(stages["terminal"], "record_digest_mismatch")

    for stage in ("execution", "delivery", "terminal"):
        key = "plan" if stage == "delivery" else "journal"
        for receipt_key in ("completed", "temporary_completed"):
            receipt = values.get((stage, receipt_key))
            if receipt is None:
                continue
            field = "plan_sha256" if stage == "delivery" else "journal_sha256"
            if receipt.get(field) != stages[stage]["files"][key].get("sha256"):
                _issue(stages[stage], "completion_digest_mismatch")
            required = {field, "result_sha256", "result_size"} if stage == "delivery" else {field}
            if set(receipt) != required:
                _issue(stages[stage], "record_shape_mismatch")
            if stage == "delivery" and (type(receipt.get("result_size")) is not int or not 0 < receipt["result_size"] <= 64 * 1024):
                _issue(stages[stage], "record_shape_mismatch")
            target_stage = "terminal" if stage == "delivery" else stage
            target_kind = "materialization_publication_committed" if target_stage == "terminal" else "materialization_execution_committed"
            if not matched[target_kind] or not stages[target_stage]["artifacts"]:
                _issue(stages[stage], "completion_without_registration")
            if stage == "delivery" and (receipt.get("result_sha256") != stages["terminal"]["files"]["marker"].get("sha256")
                or receipt.get("result_size") != stages["terminal"]["files"]["marker"].get("size")):
                _issue(stages[stage], "completion_digest_mismatch")

    for key in ("rolled_back", "temporary_rolled_back"):
        receipt = values.get(("outputs", key))
        if receipt is not None:
            if set(receipt) != {"journal_sha256"} or receipt.get("journal_sha256") != stages["outputs"]["files"]["journal"].get("sha256"):
                _issue(stages["outputs"], "rollback_digest_mismatch")
            if matched["output_publication_committed"] or matched["evolved_outputs_promoted"]:
                _issue(stages["outputs"], "rollback_with_commit_receipt")

    for name, stage in stages.items():
        relevant = [v for key, v in stage["files"].items() if key not in {"directory", "lock"}]
        any_records = any(v["state"] != "absent" for v in relevant) or any(stage["events"].values()) or stage["artifacts"]
        if name != "launch" and stage["files"]["directory"]["state"] != "absent":
            any_records = True
            if stage["files"][primary[name][0]]["state"] == "absent":
                _issue(stage, "protocol_record_missing")
        states = [v["state"] for v in stage["files"].values()]
        if "unsafe" in states or "invalid" in states or any("mismatch" in code or code.startswith("duplicate") for code in stage["issues"]):
            stage["state"] = "invalid"
        elif "unavailable" in states:
            stage["state"] = "unavailable"
        elif stage["issues"]:
            stage["state"] = "incomplete"
        else:
            stage["state"] = "present" if any_records else "absent"


def diagnose_materialization(database: Path, parent_id: str, child_id: str, *, _snapshot_data: dict | None = None) -> dict:
    """Report observations only; never call Store writers, candidate code or recovery APIs."""
    valid_ids = all(isinstance(value, str) and _SAFE_ID.fullmatch(value) for value in (parent_id, child_id))
    report = {
        "schema_version": "1", "parent_run_id": parent_id if valid_ids else None,
        "evolution_run_id": child_id if valid_ids else None, "status": "unavailable",
        "recovery_eligibility": "not_assessed", "stages": {name: _stage() for name in STAGES}, "issues": [],
    }
    try:
        if not valid_ids or parent_id == child_id:
            raise _Unavailable("diagnostic_run_identity_invalid")
        snapshot = _snapshot_data if _snapshot_data is not None else diagnostic_snapshot(database, parent_id, child_id)
        runs = {run["id"]: run for run in snapshot["runs"]}
        if set(runs) != {parent_id, child_id}:
            raise _Unavailable("diagnostic_runs_missing")
        roots = tuple(_path(runs[key]["workspace"]) for key in (parent_id, child_id))
        reader = _Reader()
        for root in roots:
            info = reader.info(root)
            if info is None or not stat.S_ISDIR(info.st_mode):
                raise _Unavailable("diagnostic_workspace_unavailable")
        suffix = hashlib.sha256(f"{parent_id}\0{child_id}".encode()).hexdigest()
        stages = report["stages"]
        with ExitStack() as stack:
            for stage, path in (
                ("launch", roots[1] / "evolution/.materialization.lock"),
                ("outputs", roots[0] / ".evolved-output-publications/.lock"),
                ("terminal", roots[1] / (_BASE + "/.terminal-publication.lock")),
            ):
                stages[stage]["files"]["lock"] = reader.lock(path, stack)
            values = _read_files(reader, stages, roots, suffix)
            matched = _ledger(snapshot, stages, parent_id, child_id, suffix)
            tasks = [task for task in snapshot["tasks"] if task["run_id"] == child_id]
            task_id = tasks[0]["id"] if len(tasks) == 1 else None
            if task_id is None:
                report["issues"].append("diagnostic_child_owner_ambiguous")
            _assess(stages, values, matched, parent_id, child_id, task_id)
            reader.verify()
            if diagnostic_snapshot(database, parent_id, child_id) != snapshot:
                raise _Unavailable("diagnostic_ledger_changed")
            reader.verify()
        report["status"] = "attention_required" if report["issues"] or any(
            stage["state"] in {"incomplete", "invalid", "unavailable"} for stage in stages.values()
        ) else "observed"
    except DiagnosticSnapshotError as exc:
        report["issues"].append(str(exc))
    except _Unavailable as exc:
        report["issues"].append(str(exc))
        if str(exc) == "diagnostic_lock_busy":
            report["status"] = "busy"
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        report["issues"].append("diagnostic_evidence_unavailable")
    if report["status"] in {"unavailable", "busy"}:
        # Partial observations must not be mistaken for a stable inspection.
        report["stages"] = {name: {**_stage(), "state": "unavailable"} for name in STAGES}
    report["next_step"] = _NEXT[report["status"]]
    return report


def format_materialization_diagnostic(report: dict) -> str:
    lines = [f"materialization inspection: {report['status']}"]
    for name, stage in report["stages"].items():
        lines.append(f"{name}: {stage['state']}")
        for key, file in stage["files"].items():
            if not key.startswith("temporary_") or file["state"] != "absent":
                lines.append(f"  {key}: {file['state']}")
        for kind, count in stage["events"].items():
            lines.append(f"  {kind}: {count}")
        for code in stage["issues"]:
            lines.append(f"  issue: {code}")
    for code in report["issues"]:
        lines.append(f"issue: {code}")
    lines.append("recovery_eligibility: not_assessed")
    lines.append(report["next_step"])
    return "\n".join(lines)
