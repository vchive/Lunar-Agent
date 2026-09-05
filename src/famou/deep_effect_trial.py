"""Matched five-round deep-evolution effect trials.

The normal effect trial deliberately measures one fresh subject session.  This module adds the
separate outer-loop measurement needed to compare the effect of WebAgent's source-default
``/evolve`` behavior without importing WebAgent or changing the normal protocol.
"""

from __future__ import annotations

import math
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import effect_trial as _normal
from .deep_feedback import (
    MAX_STAGNATION_ROUNDS,
    FeedbackError,
    build_candidate_manifest,
    build_round_feedback,
    normalize_feedback,
)
from .effect_trial import (
    EffectTrialConfig,
    EffectTrialError,
    EffectTrialReport,
    EffectTrialRunner,
)

MAX_OUTER_ROUNDS = 20
_DEEP_PROTOCOL = "famou-bench-deep-evolution-v1"
_STRATEGY = "loop"
_SAME_ATTEMPT_RESUME_ERRORS = frozenset({"incomplete_rounds"})


@dataclass(frozen=True)
class DeepEffectTrialConfig:
    """Configuration for one bounded deep-evolution effect trial."""

    base: EffectTrialConfig
    outer_rounds: int = 5
    strategy: str = _STRATEGY
    stagnation_rounds: int = 2

    def __post_init__(self) -> None:
        if not isinstance(self.base, EffectTrialConfig):
            raise EffectTrialError("deep trial base config must be an EffectTrialConfig")
        _normal._integer(self.outer_rounds, "outer_rounds", 1, MAX_OUTER_ROUNDS)
        if self.strategy != _STRATEGY:
            raise EffectTrialError("deep trial strategy must be loop")
        _normal._integer(self.stagnation_rounds, "stagnation_rounds", 1, MAX_STAGNATION_ROUNDS)

    @property
    def runs_per_case(self) -> int:
        return self.base.runs_per_case

    @property
    def timeout_seconds(self) -> float:
        return self.base.timeout_seconds

    @property
    def requested_model(self) -> str:
        return self.base.requested_model

    def safe_dict(self) -> dict[str, object]:
        return {
            **self.base.safe_dict(),
            "mode": "deep_evolution",
            "strategy": self.strategy,
            "outer_rounds": self.outer_rounds,
            "stagnation_rounds": self.stagnation_rounds,
        }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * weight)


def _score_fields(round_record: dict[str, Any]) -> bool:
    return (
        round_record["ready"]
        and round_record["extraction_status"] == "completed"
        and round_record["validity_score"] not in {None, 0.0}
        and round_record["overall_score"] is not None
    )


def _failure_statistics(records: list[dict[str, Any]], outer_rounds: int) -> dict[str, object]:
    """Aggregate bounded run/round failure counters for operational diagnostics.

    Counts are derived solely from durable logical records and their validated feedback.  They
    describe execution health; they do not alter score authority or infer a baseline.
    """

    _normal._integer(outer_rounds, "failure statistics outer rounds", 1, MAX_OUTER_ROUNDS)
    run_error_codes: dict[str, int] = {}
    round_failure_categories: dict[str, int] = {}
    round_error_codes: dict[str, int] = {}
    per_round: list[dict[str, object]] = []
    total_rounds = 0
    completed_rounds = 0
    for record in records:
        code = record.get("error_code")
        if code:
            run_error_codes[str(code)] = run_error_codes.get(str(code), 0) + 1
        for item in record.get("rounds", []):
            total_rounds += 1
            if item.get("status") == "completed":
                completed_rounds += 1
            feedback = item.get("feedback") or {}
            category = feedback.get("failure_category")
            if category:
                key = str(category)
                round_failure_categories[key] = round_failure_categories.get(key, 0) + 1
            round_code = item.get("error_code")
            if round_code:
                key = str(round_code)
                round_error_codes[key] = round_error_codes.get(key, 0) + 1
    # Sort keys before returning so this projection remains deterministic even if a caller passes
    # records in a different order. The records themselves are already validated by the runner.
    run_error_codes = dict(sorted(run_error_codes.items()))
    round_failure_categories = dict(sorted(round_failure_categories.items()))
    round_error_codes = dict(sorted(round_error_codes.items()))
    for round_index in range(1, outer_rounds + 1):
        items = [
            item
            for record in records
            for item in record.get("rounds", [])
            if item.get("round_index") == round_index
        ]
        categories: dict[str, int] = {}
        for item in items:
            category = (item.get("feedback") or {}).get("failure_category")
            if category:
                key = str(category)
                categories[key] = categories.get(key, 0) + 1
        per_round.append(
            {
                "round_index": round_index,
                "recorded": len(items),
                "completed": sum(1 for item in items if item.get("status") == "completed"),
                "failure_categories": dict(sorted(categories.items())),
            }
        )
    return {
        "runs": len(records),
        "failed_runs": sum(1 for record in records if record.get("status") == "failed"),
        "run_error_codes": run_error_codes,
        "rounds": total_rounds,
        "completed_rounds": completed_rounds,
        "round_failure_categories": round_failure_categories,
        "round_error_codes": round_error_codes,
        "timeout_count": run_error_codes.get("process_timeout", 0)
        + round_error_codes.get("process_timeout", 0),
        "per_round": per_round,
    }


class DeepEffectTrialRunner(EffectTrialRunner):
    """Run a recoverable one/two-case, bounded outer-loop effect trial."""

    def __init__(
        self,
        suite_path: str | Path,
        baseline_path: str | Path,
        workspace: str | Path,
        *,
        case_sources: dict[str, str | Path],
        config: DeepEffectTrialConfig,
        resume: bool = False,
        process_executor: _normal.ProcessExecutor | None = None,
    ) -> None:
        self.deep_config = config
        super().__init__(
            suite_path,
            baseline_path,
            workspace,
            case_sources=case_sources,
            config=config.base,
            resume=resume,
            process_executor=process_executor,
        )

    def _identity(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "protocol": _DEEP_PROTOCOL,
            "mode": "deep_evolution",
            "strategy": self.deep_config.strategy,
            "outer_rounds": self.deep_config.outer_rounds,
            "suite_sha256": self.suite_sha256,
            "baseline_sha256": self.baseline_sha256,
            "case_keys": [value.key for value in self.suite.cases],
            "config": self.deep_config.safe_dict(),
        }

    def _subject_receipt(
        self,
        path: Path,
        round_index: int,
        *,
        expected_request_sha256: str | None = None,
        require_request_sha256: bool = False,
    ) -> dict[str, Any]:
        payload, _ = _normal._read_json(path, "deep subject receipt", _normal.MAX_RECEIPT_BYTES)
        fields = {
            "schema_version",
            "mode",
            "status",
            "requested_model",
            "effective_model",
            "model_evidence",
            "interaction_turns",
            "usage",
            "round_index",
            "outer_rounds",
        }
        # `request_sha256` was added after the initial deep protocol.  Accepting the old shape
        # keeps completed Feature 051 records readable, while every newly produced built-in
        # receipt carries the binding and resumed partial rounds require it.
        if not isinstance(payload, dict) or set(payload) not in (
            fields,
            fields | {"request_sha256"},
        ):
            raise EffectTrialError("deep subject receipt must contain the expected fields")
        item = dict(payload)
        receipt_round = _normal._integer(item["round_index"], "deep subject receipt round", 1, MAX_OUTER_ROUNDS)
        receipt_outer = _normal._integer(item["outer_rounds"], "deep subject receipt outer rounds", 1, MAX_OUTER_ROUNDS)
        if (
            item["schema_version"] != "1"
            or item["mode"] != "deep_evolution"
            or item["status"] != "completed"
            or receipt_round != round_index
            or receipt_outer != self.deep_config.outer_rounds
        ):
            raise EffectTrialError("deep subject receipt does not describe the requested round")
        if item["requested_model"] != self.deep_config.requested_model:
            raise EffectTrialError("deep subject requested model does not match frozen config")
        effective = _normal._text(item["effective_model"], "deep subject effective model")
        evidence = _normal._text(item["model_evidence"], "deep subject model evidence", safe_id=True)
        if evidence not in _normal._MODEL_EVIDENCE:
            raise EffectTrialError("deep subject model evidence is unsupported")
        request_sha256 = None
        if "request_sha256" in item:
            request_sha256 = _normal._digest(
                item["request_sha256"], "deep subject request sha256"
            )
        if expected_request_sha256 is not None:
            if request_sha256 is None and require_request_sha256:
                raise EffectTrialError("deep subject receipt request digest is missing")
            if request_sha256 is not None and request_sha256 != expected_request_sha256:
                raise EffectTrialError("deep subject receipt request digest disagrees with request")
        result = {
            "requested_model": item["requested_model"],
            "effective_model": effective,
            "model_evidence": evidence,
            "interaction_turns": _normal._integer(
                item["interaction_turns"], "deep subject interaction turns", 0, _normal.MAX_TURNS
            ),
            "usage": self._validate_usage(item["usage"]),
        }
        if request_sha256 is not None:
            result["request_sha256"] = request_sha256
        return result

    def _validate_round(self, payload: object, case: _normal.TrialCase, run_index: int, round_index: int) -> dict[str, Any]:
        fields = {
            "round_index",
            "status",
            "ready",
            "subject_receipt",
            "harness_receipt",
            "requested_model",
            "effective_model",
            "model_evidence",
            "interaction_turns",
            "usage",
            "extraction_status",
            "validity_score",
            "overall_score",
            "quality_score",
            "detail_metrics",
            "error_code",
        }
        optional_request_fields = (
            set(),
            {"request_sha256"},
            {"harness_request_sha256"},
            {"request_sha256", "harness_request_sha256"},
        )
        allowed = tuple(
            fields | optional | feedback
            for optional in optional_request_fields
            for feedback in (set(), {"feedback"})
        )
        if not isinstance(payload, dict) or set(payload) not in allowed:
            raise EffectTrialError("deep round record must contain the expected fields")
        item = dict(payload)
        round_value = _normal._integer(item["round_index"], "deep round index", 1, MAX_OUTER_ROUNDS)
        if round_value != round_index or item["status"] not in {"completed", "failed"}:
            raise EffectTrialError("deep round identity or status is invalid")
        if not isinstance(item["ready"], bool):
            raise EffectTrialError("deep round ready must be boolean")
        if item["ready"] != (item["status"] == "completed"):
            raise EffectTrialError("deep round status and ready disagree")
        for name in ("subject_receipt", "harness_receipt"):
            _normal._relative_path(item[name], f"deep round {name}")
        for name in ("requested_model", "effective_model", "model_evidence", "extraction_status", "error_code"):
            value = item[name]
            if value is not None:
                _normal._text(value, f"deep round {name}", safe_id=name in {"model_evidence", "extraction_status", "error_code"})
        if item["interaction_turns"] is not None:
            _normal._integer(item["interaction_turns"], "deep round interaction turns", 0, _normal.MAX_TURNS)
        if item["usage"] is not None:
            self._validate_usage(item["usage"])
        if "request_sha256" in item:
            _normal._digest(item["request_sha256"], "deep round request sha256")
        if "harness_request_sha256" in item:
            _normal._digest(item["harness_request_sha256"], "deep round harness request sha256")
        _normal._validity(item["validity_score"], "deep round validity", nullable=True)
        _normal._number(item["overall_score"], "deep round score", nullable=True)
        _normal._number(item["quality_score"], "deep round quality", nullable=True)
        if not isinstance(item["detail_metrics"], dict) or len(_normal._canonical_bytes(item["detail_metrics"])) > 16 * 1024:
            raise EffectTrialError("deep round detail metrics are invalid")
        if "feedback" in item:
            try:
                item["feedback"] = normalize_feedback(item["feedback"], expected_round=round_index)
            except FeedbackError as exc:
                raise EffectTrialError(f"deep round feedback is invalid: {exc}") from exc
        else:
            try:
                item["feedback"] = normalize_feedback(
                    {
                        "round_index": round_index,
                        "validity_score": item["validity_score"],
                        "overall_score": item["overall_score"],
                        "quality_score": item["quality_score"],
                    },
                    expected_round=round_index,
                )
            except FeedbackError as exc:
                raise EffectTrialError(f"deep round legacy feedback is invalid: {exc}") from exc
        del case, run_index
        return item

    def _validate_deep_record(self, payload: object, case: _normal.TrialCase, run_index: int) -> dict[str, Any]:
        item = _normal._strict_object(
            payload,
            {
                "schema_version", "case_key", "run_index", "attempt", "status", "ready",
                "elapsed_ms", "requested_model", "effective_model", "model_evidence",
                "interaction_turns", "usage", "extraction_status", "validity_score",
                "overall_score", "quality_score", "detail_metrics", "error_code",
                "outer_rounds", "rounds",
            },
            "deep logical run record",
        )
        if item["schema_version"] != "1" or item["case_key"] != case.key or item["run_index"] != run_index:
            raise EffectTrialError("deep logical run identity mismatch")
        outer_rounds = _normal._integer(item["outer_rounds"], "deep logical run outer rounds", 1, MAX_OUTER_ROUNDS)
        if outer_rounds != self.deep_config.outer_rounds:
            raise EffectTrialError("deep logical run outer-round identity mismatch")
        _normal._relative_path(item["attempt"], "deep logical run attempt")
        if item["status"] not in {"completed", "failed"} or not isinstance(item["ready"], bool):
            raise EffectTrialError("deep logical run status is invalid")
        if item["ready"] != (item["status"] == "completed"):
            raise EffectTrialError("deep logical run status and ready disagree")
        _normal._integer(item["elapsed_ms"], "deep logical run elapsed_ms", 0, 172_800_000)
        for name in ("requested_model", "effective_model", "model_evidence", "extraction_status", "error_code"):
            value = item[name]
            if value is not None:
                _normal._text(value, f"deep logical run {name}", safe_id=name in {"model_evidence", "extraction_status", "error_code"})
        if item["interaction_turns"] is not None:
            _normal._integer(item["interaction_turns"], "deep logical run interaction turns", 0, _normal.MAX_TURNS)
        if item["usage"] is not None:
            self._validate_usage(item["usage"])
        for name in ("validity_score", "overall_score", "quality_score"):
            _normal._number(item[name], f"deep logical run {name}", nullable=True)
        if not isinstance(item["detail_metrics"], dict) or len(_normal._canonical_bytes(item["detail_metrics"])) > 16 * 1024:
            raise EffectTrialError("deep logical run detail metrics are invalid")
        rounds = item["rounds"]
        if not isinstance(rounds, list) or not 0 <= len(rounds) <= self.deep_config.outer_rounds:
            raise EffectTrialError("deep logical run rounds are invalid")
        expected = list(range(1, len(rounds) + 1))
        normalized_rounds: list[dict[str, Any]] = []
        for index, value in enumerate(rounds, start=1):
            parsed = self._validate_round(value, case, run_index, index)
            if parsed["round_index"] != expected[index - 1]:
                raise EffectTrialError("deep logical run rounds must be ordered")
            normalized_rounds.append(parsed)
        if item["ready"] and len(rounds) != self.deep_config.outer_rounds:
            raise EffectTrialError("ready deep logical run must contain every outer round")
        item["rounds"] = normalized_rounds
        return item

    def _verify_round_artifacts(self, case: _normal.TrialCase, record: dict[str, Any]) -> None:
        """Re-read receipt files so resume cannot rely on a stale logical record alone."""
        raw_attempt = self.workspace / record["attempt"]
        _normal._reject_symlink_components(raw_attempt, self.workspace, "deep attempt path")
        attempt = raw_attempt.resolve(strict=False)
        try:
            attempt.relative_to(self.workspace)
        except ValueError as exc:
            raise EffectTrialError("deep attempt path escapes trial workspace") from exc
        if attempt.is_symlink() or not attempt.is_dir():
            raise EffectTrialError("deep attempt directory is missing or unsafe")
        for round_record in record["rounds"]:
            round_index = int(round_record["round_index"])
            subject_root = attempt / "subject"
            receipts_root = subject_root / "receipts"
            harness_root = attempt / f"harness-{round_index:03d}"
            if (
                subject_root.is_symlink()
                or not subject_root.is_dir()
                or receipts_root.is_symlink()
                or not receipts_root.is_dir()
                or harness_root.is_symlink()
                or not harness_root.is_dir()
            ):
                raise EffectTrialError("deep round artifact workspace is missing or unsafe")
            subject_path = receipts_root / f"{round_index:03d}.json"
            harness_path = harness_root / "receipt.json"
            subject = self._subject_receipt(
                subject_path,
                round_index,
                expected_request_sha256=round_record.get("request_sha256"),
                require_request_sha256="request_sha256" in round_record,
            )
            scored = self._harness_receipt(harness_path, case)
            harness_request_sha256 = round_record.get("harness_request_sha256")
            if harness_request_sha256 is not None:
                harness_request_path = harness_root / "request.json"
                try:
                    _, harness_request_bytes = _normal._read_json(
                        harness_request_path,
                        "deep harness request",
                        _normal.MAX_RECEIPT_BYTES,
                    )
                except EffectTrialError as exc:
                    raise EffectTrialError("deep harness request disagrees with logical record") from exc
                if _normal._hash_bytes(harness_request_bytes) != harness_request_sha256:
                    raise EffectTrialError("deep harness request disagrees with logical record")
            for name in (
                "requested_model",
                "effective_model",
                "model_evidence",
                "interaction_turns",
                "usage",
            ):
                if subject[name] != round_record[name]:
                    raise EffectTrialError("deep subject receipt disagrees with logical record")
            for name in (
                "extraction_status",
                "validity_score",
                "overall_score",
                "quality_score",
                "detail_metrics",
            ):
                if scored[name] != round_record[name]:
                    raise EffectTrialError("deep harness receipt disagrees with logical record")

    def _load_record(self, case: _normal.TrialCase, run_index: int, state: dict[str, Any]) -> dict[str, Any] | None:
        path = self._record_path(case, run_index)
        key = self._record_key(case, run_index)
        _normal._reject_symlink_components(path, self.workspace, "deep logical run record path")
        if not path.exists():
            if key in state["records"]:
                raise EffectTrialError(f"logical run record is missing despite frozen state: {key}")
            return None
        # Only state-registered records are authoritative. A subject can reach sibling run paths
        # within the documented same-user capability boundary. Execute a new independently scored
        # attempt; the earlier attempt directory remains as evidence when its record is replaced.
        if key not in state["records"]:
            return None
        payload, canonical = _normal._read_json(path, "deep logical run record", _normal.MAX_RECEIPT_BYTES)
        expected = state["records"][key]
        actual = _normal._hash_bytes(canonical)
        if actual != expected:
            backup = self._record_backup_path(case, run_index)
            try:
                previous, previous_canonical = _normal._read_json(
                    backup,
                    "previous deep logical run record",
                    _normal.MAX_RECEIPT_BYTES,
                )
            except EffectTrialError as exc:
                raise EffectTrialError(f"logical run record digest mismatch: {key}") from exc
            if _normal._hash_bytes(previous_canonical) != expected:
                raise EffectTrialError(f"logical run record digest mismatch: {key}")
            parsed = self._validate_deep_record(previous, case, run_index)
            _normal._atomic_json(path, previous, _normal.MAX_RECEIPT_BYTES)
            backup.unlink()
            return parsed
        parsed = self._validate_deep_record(payload, case, run_index)
        return parsed

    def _store_record(self, case: _normal.TrialCase, run_index: int, record: dict[str, Any], state: dict[str, Any]) -> None:
        self._validate_deep_record(record, case, run_index)
        self._commit_record(case, run_index, record, state)

    def _failed_deep_record(
        self,
        case: _normal.TrialCase,
        run_index: int,
        attempt_index: int,
        started: float,
        rounds: list[dict[str, Any]],
        code: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "case_key": case.key,
            "run_index": run_index,
            "attempt": f"cases/{case.key}/runs/{run_index:03d}/attempts/{attempt_index:03d}",
            "status": "failed",
            "ready": False,
            "elapsed_ms": self._elapsed(started),
            "requested_model": self.deep_config.requested_model,
            "effective_model": None,
            "model_evidence": None,
            "interaction_turns": None,
            "usage": None,
            "extraction_status": None,
            "validity_score": None,
            "overall_score": None,
            "quality_score": None,
            "detail_metrics": {},
            "error_code": code,
            "outer_rounds": self.deep_config.outer_rounds,
            "rounds": rounds,
        }

    def _aggregate_record(
        self,
        case: _normal.TrialCase,
        run_index: int,
        attempt_index: int,
        started: float,
        rounds: list[dict[str, Any]],
        *,
        status: str,
        ready: bool,
        error_code: str | None,
    ) -> dict[str, Any]:
        valid = [value for value in rounds if _score_fields(value)]
        winner = max(
            valid,
            key=lambda value: (float(value["overall_score"]), -int(value["round_index"])),
            default=None,
        )
        effective_models = [value["effective_model"] for value in rounds]
        evidences = [value["model_evidence"] for value in rounds]
        interactions = [value["interaction_turns"] for value in rounds]
        usages = [value["usage"] for value in rounds]
        usage = None
        if usages and all(value is not None for value in usages):
            usage = {
                key: sum(int(value[key]) for value in usages if value is not None)
                for key in ("input_tokens", "output_tokens", "total_tokens")
            }
        return {
            "schema_version": "1",
            "case_key": case.key,
            "run_index": run_index,
            "attempt": f"cases/{case.key}/runs/{run_index:03d}/attempts/{attempt_index:03d}",
            "status": status,
            "ready": ready,
            "elapsed_ms": self._elapsed(started),
            "requested_model": self.deep_config.requested_model,
            "effective_model": effective_models[0] if effective_models and len(set(effective_models)) == 1 else None,
            "model_evidence": evidences[0] if evidences and len(set(evidences)) == 1 else None,
            "interaction_turns": sum(interactions) if interactions and all(value is not None for value in interactions) else None,
            "usage": usage,
            "extraction_status": winner["extraction_status"] if winner else None,
            "validity_score": winner["validity_score"] if winner else None,
            "overall_score": winner["overall_score"] if winner else None,
            "quality_score": winner["quality_score"] if winner else None,
            "detail_metrics": winner["detail_metrics"] if winner else {},
            "error_code": error_code,
            "outer_rounds": self.deep_config.outer_rounds,
            "rounds": rounds,
        }

    def _execute_run(
        self,
        case: _normal.TrialCase,
        run_index: int,
        *,
        state: dict[str, Any],
        resume_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if resume_record is None:
            attempt_root, attempt_index = self._attempt_root(case, run_index)
            rounds: list[dict[str, Any]] = []
        else:
            raw_attempt = self.workspace / resume_record["attempt"]
            _normal._reject_symlink_components(
                raw_attempt, self.workspace, "deep resume attempt path"
            )
            attempt_path = raw_attempt.resolve(strict=False)
            try:
                attempt_path.relative_to(self.workspace)
            except ValueError as exc:
                raise EffectTrialError("deep attempt path escapes trial workspace") from exc
            if attempt_path.is_symlink() or not attempt_path.is_dir() or not attempt_path.name.isdigit():
                raise EffectTrialError("deep resume attempt directory is invalid")
            attempt_root = attempt_path
            attempt_index = int(attempt_path.name)
            rounds = [dict(value) for value in resume_record["rounds"]]
        subject_root = attempt_root / "subject"
        if subject_root.is_symlink() or (subject_root.exists() and not subject_root.is_dir()):
            raise EffectTrialError("deep subject workspace is missing or unsafe")
        subject_root.mkdir(exist_ok=True)
        started = time.monotonic()
        previous: dict[str, object] | None = None
        if rounds:
            latest = rounds[-1]
            previous = dict(latest["feedback"])
        try:
            if resume_record is None:
                self._stage_public_case(case, subject_root)
            for round_index in range(len(rounds) + 1, self.deep_config.outer_rounds + 1):
                subject_request = {
                    "schema_version": "1",
                    "mode": "deep_evolution",
                    "benchmark": self.suite.benchmark.to_dict(),
                    "case": case.public_identity(),
                    "run_index": run_index,
                    "round_index": round_index,
                    "outer_rounds": self.deep_config.outer_rounds,
                    "requested_model": self.deep_config.requested_model,
                    "entrypoint": case.entrypoint,
                    "public_files": [value.to_dict() for value in case.public_files],
                    "previous_evaluation": previous,
                    "receipt_path": f"receipts/{round_index:03d}.json",
                }
                request_bytes = _normal._atomic_json(subject_root / "request.json", subject_request, _normal.MAX_RECEIPT_BYTES)
                request_sha256 = _normal._hash_bytes(request_bytes)
                self._verify_staged_case(case, subject_root, request_sha256)
                subject_receipt_path = subject_root / f"receipts/{round_index:03d}.json"
                harness_root = attempt_root / f"harness-{round_index:03d}"
                # `Path.exists()` is false for a dangling symlink; include `is_symlink()` so a
                # malicious preseed cannot fall through to an uncaught mkdir error.
                harness_preexisting = harness_root.exists() or harness_root.is_symlink()
                subject_receipt_preexisting = (
                    subject_receipt_path.exists() or subject_receipt_path.is_symlink()
                )
                if subject_receipt_preexisting:
                    # A process may have exited after writing its score-free receipt but before
                    # the harness started. Reuse that completed subject round on resume.
                    if resume_record is None:
                        raise EffectTrialError("deep subject receipt already exists")
                    if harness_preexisting and (
                        harness_root.is_symlink() or not harness_root.is_dir()
                    ):
                        raise EffectTrialError("deep_resume_artifact_order_invalid")
                    subject = self._subject_receipt(
                        subject_receipt_path,
                        round_index,
                        expected_request_sha256=request_sha256,
                        require_request_sha256=True,
                    )
                else:
                    if harness_preexisting:
                        # A harness request/receipt cannot legitimately precede the score-free
                        # subject receipt. Invoking the subject here would let it populate a stale
                        # harness directory and smuggle a score into the resumed round.
                        code = (
                            "subject_created_harness_workspace"
                            if resume_record is None
                            else "deep_resume_artifact_order_invalid"
                        )
                        raise EffectTrialError(code)
                    self._invoke(
                        self.deep_config.base.subject_command,
                        subject_root / "request.json",
                        cwd=subject_root,
                        environment=self.deep_config.base.subject_environment,
                    )
                    if harness_root.exists() or harness_root.is_symlink():
                        # The subject may write candidate artifacts only inside its own workspace;
                        # creating the sibling harness directory is a score-authority violation.
                        raise EffectTrialError("subject_created_harness_workspace")
                    subject = None
                self._verify_control_copy("suite.json", self.suite_sha256)
                self._verify_control_copy("baseline.json", self.baseline_sha256)
                self._verify_staged_case(case, subject_root, request_sha256)
                if subject is None:
                    subject = self._subject_receipt(
                        subject_receipt_path,
                        round_index,
                        expected_request_sha256=request_sha256,
                    )

                harness_request = {
                    "schema_version": "1",
                    "candidate_workspace": "../subject",
                    "run_index": run_index,
                    "benchmark": self.suite.benchmark.to_dict(),
                    "evaluation_profile": self.suite.evaluation_profile.to_dict(),
                    "case": case.public_identity(),
                    "harness": case.harness.to_dict(),
                    "receipt_path": "receipt.json",
                }
                harness_request_bytes = _normal._canonical_bytes(harness_request)
                if len(harness_request_bytes) > _normal.MAX_RECEIPT_BYTES:
                    raise EffectTrialError("harness request exceeds its bounded size")
                harness_request_sha256 = _normal._hash_bytes(harness_request_bytes)
                if harness_root.exists() or harness_root.is_symlink():
                    if harness_root.is_symlink() or not harness_root.is_dir():
                        raise EffectTrialError("deep_resume_artifact_order_invalid")
                    # A harness result is authoritative only after its round record is durable.
                    # If interruption left an unrecorded harness directory, discard it and rerun
                    # the private harness; otherwise a subject-created receipt could be reused.
                    shutil.rmtree(harness_root)
                harness_root.mkdir()
                _normal._atomic_json(
                    harness_root / "request.json", harness_request, _normal.MAX_RECEIPT_BYTES
                )
                self._invoke(
                    self.deep_config.base.harness_command,
                    harness_root / "request.json",
                    cwd=harness_root,
                    environment=self.deep_config.base.harness_environment,
                )
                self._verify_control_copy("suite.json", self.suite_sha256)
                self._verify_control_copy("baseline.json", self.baseline_sha256)
                self._verify_staged_case(case, subject_root, request_sha256)
                scored = self._harness_receipt(harness_root / "receipt.json", case)
                try:
                    feedback = build_round_feedback(
                        round_index,
                        scored,
                        candidate_manifest=build_candidate_manifest(subject_root),
                        prior_rounds=rounds,
                        stagnation_rounds=self.deep_config.stagnation_rounds,
                    )
                except FeedbackError as exc:
                    raise EffectTrialError("feedback_contract_failed") from exc
                round_record = {
                    "round_index": round_index,
                    "status": "completed",
                    "ready": True,
                    "subject_receipt": f"cases/{case.key}/runs/{run_index:03d}/attempts/{attempt_index:03d}/subject/receipts/{round_index:03d}.json",
                    "harness_receipt": f"cases/{case.key}/runs/{run_index:03d}/attempts/{attempt_index:03d}/harness-{round_index:03d}/receipt.json",
                    **subject,
                    **scored,
                    "harness_request_sha256": harness_request_sha256,
                    "feedback": feedback,
                    "error_code": None,
                }
                rounds.append(round_record)
                previous = dict(feedback)
                # Persist a failed/incomplete logical record after every successful round. If the
                # process is interrupted before the next round, resume can continue from this
                # prefix while preserving the old attempt directory.
                self._store_record(
                    case,
                    run_index,
                    self._aggregate_record(
                        case,
                        run_index,
                        attempt_index,
                        started,
                        rounds,
                        status="failed",
                        ready=False,
                        error_code="incomplete_rounds",
                    ),
                    state,
                )
        except EffectTrialError as exc:
            code = str(exc)
            if code.startswith(("frozen ", "case source")) or "public" in code:
                raise
            if code not in {
                "process_timeout",
                "process_start_failed",
                "process_result_invalid",
                "process_nonzero_exit",
                "deep subject receipt does not describe the requested round",
                "deep subject requested model does not match frozen config",
                "subject_created_harness_workspace",
                "deep_resume_artifact_order_invalid",
                "feedback_contract_failed",
            }:
                code = "deep_trial_boundary_failed"
            return self._failed_deep_record(case, run_index, attempt_index, started, rounds, code)

        return self._aggregate_record(
            case,
            run_index,
            attempt_index,
            started,
            rounds,
            status="completed",
            ready=True,
            error_code=None,
        )

    def _case_report(self, case: _normal.TrialCase, records: list[dict[str, Any]]) -> dict[str, Any]:
        baseline = next(value for value in self.baseline.cases if value.key == case.key)
        ready = [value for value in records if value["ready"]]
        valid = [value for value in ready if value["overall_score"] is not None and value["validity_score"] not in {None, 0.0}]
        scores = [float(value["overall_score"]) for value in valid]
        validity = [float(value["validity_score"]) for value in valid if value["validity_score"] is not None]
        quality = [float(value["quality_score"]) for value in valid if value["quality_score"] is not None]
        lunar_best = max(scores, default=None)
        historical_best = baseline.best()
        delta = lunar_best - historical_best if lunar_best is not None and historical_best is not None else None
        breakthrough = delta is not None and delta > 0
        model_match = bool(ready) and all(
            value["requested_model"] == self.baseline.model.requested
            and value["effective_model"] == self.baseline.model.effective
            for value in ready
        )
        milestone = breakthrough and len(ready) == self.config.runs_per_case and model_match
        curve: list[dict[str, object]] = []
        for round_index in range(1, self.deep_config.outer_rounds + 1):
            round_values = [
                round_record
                for record in records
                for round_record in record["rounds"]
                if round_record["round_index"] == round_index
            ]
            valid_rounds = [value for value in round_values if _score_fields(value)]
            round_scores = [float(value["overall_score"]) for value in valid_rounds]
            round_validity = [float(value["validity_score"]) for value in valid_rounds if value["validity_score"] is not None]
            round_quality = [float(value["quality_score"]) for value in valid_rounds if value["quality_score"] is not None]
            curve.append(
                {
                    "round_index": round_index,
                    "evaluated_runs": len(round_values),
                    "valid_runs": len(valid_rounds),
                    "best": max(round_scores, default=None),
                    "score_p50": _percentile(round_scores, 0.50),
                    "score_p90": _percentile(round_scores, 0.90),
                    "validity_p50": _percentile(round_validity, 0.50),
                    "quality_p50": _percentile(round_quality, 0.50),
                }
            )
        first_best = curve[0]["best"] if curve else None
        gain = lunar_best - float(first_best) if lunar_best is not None and first_best is not None else None
        projected = []
        for value in records:
            projected.append(
                {
                    "run_index": value["run_index"],
                    "status": value["status"],
                    "ready": value["ready"],
                    "elapsed_ms": value["elapsed_ms"],
                    "requested_model": value["requested_model"],
                    "effective_model": value["effective_model"],
                    "model_evidence": value["model_evidence"],
                    "interaction_turns": value["interaction_turns"],
                    "usage": value["usage"],
                    "extraction_status": value["extraction_status"],
                    "validity_score": value["validity_score"],
                    "overall_score": value["overall_score"],
                    "quality_score": value["quality_score"],
                    "detail_metrics": value["detail_metrics"],
                    "error_code": value["error_code"],
                    "attempt": value["attempt"],
                    "rounds": [
                        {
                            "round_index": item["round_index"],
                            "status": item["status"],
                            "ready": item["ready"],
                            "extraction_status": item["extraction_status"],
                            "validity_score": item["validity_score"],
                            "overall_score": item["overall_score"],
                            "quality_score": item["quality_score"],
                            "error_code": item["error_code"],
                            "feedback": {
                                "directive": item["feedback"]["directive"],
                                "failure_category": item["feedback"]["failure_category"],
                                "stagnation": item["feedback"]["stagnation"],
                                "score_delta": item["feedback"]["score_delta"],
                                "best_overall_score": item["feedback"]["best_overall_score"],
                                "best_round_index": item["feedback"]["best_round_index"],
                            },
                        }
                        for item in value["rounds"]
                    ],
                }
            )
        return {
            "key": case.key,
            "revision_id": case.revision_id,
            "digest": case.digest,
            "harness": case.harness.to_dict(),
            "planned_runs": self.config.runs_per_case,
            "ready_runs": len(ready),
            "valid_runs": len(valid),
            "valid_rate": len(valid) / len(ready) if ready else None,
            "lunar_best": lunar_best,
            "webagent_historical_best": historical_best,
            "score_delta": delta,
            "score_breakthrough": breakthrough,
            "model_identity_match": model_match,
            "milestone_achieved": milestone,
            "score_p50": _percentile(scores, 0.50),
            "score_p90": _percentile(scores, 0.90),
            "validity_p50": _percentile(validity, 0.50),
            "validity_p90": _percentile(validity, 0.90),
            "quality_p50": _percentile(quality, 0.50),
            "quality_p90": _percentile(quality, 0.90),
            "gain_from_first_round": gain,
            "feedback_directives": {
                directive: sum(
                    1
                    for record in records
                    for item in record["rounds"]
                    if item["feedback"]["directive"] == directive
                )
                for directive in (
                    "refine_best",
                    "repair_validity",
                    "repair_evaluation",
                    "change_search_strategy",
                    "preserve_best_and_probe",
                )
            },
            "failure_statistics": _failure_statistics(records, self.deep_config.outer_rounds),
            "round_curve": curve,
            "runs": projected,
        }

    def run(self) -> EffectTrialReport:
        if self._started:
            raise EffectTrialError("effect trial runner can only be run once")
        self._started = True
        self._verify_sources()
        state = self._prepare_state()
        case_reports: list[dict[str, Any]] = []
        for case in self.suite.cases:
            records: list[dict[str, Any]] = []
            for run_index in range(1, self.config.runs_per_case + 1):
                record = self._load_record(case, run_index, state)
                # A failed deep run may have a durable completed-round prefix. Verify its receipts
                # before deciding whether the attempt itself is safe to continue.
                if record is not None and record["status"] == "failed":
                    if record["rounds"]:
                        self._verify_round_artifacts(case, record)
                    # Only a cleanly persisted completed-round prefix may reuse an attempt.
                    # Boundary/process failures can leave subject-controlled sibling artifacts,
                    # so an explicit resume retries them in a new attempt and preserves the old
                    # directory as evidence.
                    resume_record = (
                        record
                        if record["error_code"] in _SAME_ATTEMPT_RESUME_ERRORS
                        else None
                    )
                    record = None
                else:
                    resume_record = None
                if record is None:
                    record = self._execute_run(
                        case,
                        run_index,
                        state=state,
                        resume_record=resume_record,
                    )
                    self._store_record(case, run_index, record, state)
                records.append(record)
            case_reports.append(self._case_report(case, records))
        self._verify_sources()
        self._verify_control_copy("suite.json", self.suite_sha256)
        self._verify_control_copy("baseline.json", self.baseline_sha256)
        self._verify_registered_records(state)
        for case in self.suite.cases:
            for run_index in range(1, self.config.runs_per_case + 1):
                record = self._load_record(case, run_index, state)
                if record is not None:
                    self._verify_round_artifacts(case, record)
        achieved = [value["key"] for value in case_reports if value["milestone_achieved"]]
        ready_runs = [
            run
            for case in case_reports
            for run in case["runs"]
            if run["ready"]
        ]
        provider_observed = self.baseline.model.evidence == "provider_observed" and bool(ready_runs) and all(
            run["model_evidence"] == "provider_observed"
            for run in ready_runs
        )
        limitations = [
            "selected_cases_do_not_establish_suite_parity",
            "best_of_n_is_not_a_statistical_superiority_test",
            "five_round_local_loop_is_not_webagent_prompt_identity",
            "process_capability_separation_is_not_an_os_sandbox",
        ]
        report_payload = {
            "schema_version": "1",
            "protocol": _DEEP_PROTOCOL,
            "mode": "deep_evolution",
            "strategy": self.deep_config.strategy,
            "outer_rounds": self.deep_config.outer_rounds,
            "webagent_source_default_outer_rounds": 5,
            "suite_sha256": self.suite_sha256,
            "baseline_sha256": self.baseline_sha256,
            "benchmark": self.suite.benchmark.to_dict(),
            "evaluation_profile": self.suite.evaluation_profile.to_dict(),
            "baseline": {
                "source": self.baseline.source,
                "experiment_id": self.baseline.experiment_id,
                "authority": self.baseline.authority,
                "mode": "normal",
                "model": self.baseline.model.to_dict(),
            },
            "config": self.deep_config.safe_dict(),
            "cases": case_reports,
            "milestone": {"achieved": bool(achieved), "case_keys": achieved},
            "comparability": {
                "kind": "descriptive_same_frozen_harness_deep_evolution",
                "model_identity_evidence": "provider_observed" if provider_observed else "not_provider_observed",
                "formal_conclusion_eligibility": "ineligible",
                "baseline_conclusion_eligibility": self.baseline.conclusion_eligibility,
                "limitations": limitations,
            },
        }
        _normal._atomic_json(self.workspace / "report.json", report_payload, _normal.MAX_MANIFEST_BYTES)
        return EffectTrialReport(report_payload)


__all__ = ["MAX_OUTER_ROUNDS", "DeepEffectTrialConfig", "DeepEffectTrialRunner"]
