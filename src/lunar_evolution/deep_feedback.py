"""Bounded, score-authority-neutral feedback for deep evolution rounds.

The private harness remains the only component allowed to produce a score.  This module only
projects already-authorized harness fields and candidate metadata into the small contract that a
fresh subject session may see.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

MAX_MANIFEST_ENTRIES = 64
MAX_MANIFEST_FILE_BYTES = 64 * 1024 * 1024
MAX_FEEDBACK_BYTES = 16 * 1024
MAX_STAGNATION_ROUNDS = 10
SAFE_DETAIL_METRIC_NAMES = frozenset(
    {"cost", "cost_time", "feasibility", "objective", "quality", "runtime", "score", "validity"}
)
FAILURE_CATEGORIES = frozenset({"none", "invalid_candidate", "evaluation_failed", "score_unavailable"})
DIRECTIVES = frozenset(
    {"refine_best", "repair_validity", "repair_evaluation", "change_search_strategy", "preserve_best_and_probe"}
)
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class FeedbackError(ValueError):
    """A deep-round feedback object violates the bounded contract."""


def _strict_object(value: object, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise FeedbackError(f"{label} must contain exactly: {', '.join(sorted(fields))}")
    return value


def _finite(value: object, label: str, *, nullable: bool = False) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        suffix = " or null" if nullable else ""
        raise FeedbackError(f"{label} must be finite{suffix}")
    return float(value)


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise FeedbackError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def _path(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\x00" in value
        or len(value.encode("utf-8")) > 512
    ):
        raise FeedbackError(f"{label} must be a bounded POSIX relative path")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise FeedbackError(f"{label} must be a bounded POSIX relative path")
    if path.parts[0] == "case" or path.parts[0] == "receipts" or value == "request.json":
        raise FeedbackError(f"{label} contains a control or public-case path")
    return path.as_posix()


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise FeedbackError(f"{label} must be a SHA-256 digest")
    return value


def _validate_manifest(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) > MAX_MANIFEST_ENTRIES:
        raise FeedbackError("candidate_manifest must be a bounded array")
    result: list[dict[str, object]] = []
    paths: set[str] = set()
    for entry in value:
        item = _strict_object(entry, {"path", "size_bytes", "sha256"}, "candidate manifest entry")
        path = _path(item["path"], "candidate manifest path")
        if path in paths:
            raise FeedbackError("candidate manifest contains duplicate paths")
        paths.add(path)
        result.append(
            {
                "path": path,
                "size_bytes": _integer(item["size_bytes"], "candidate manifest size", 0, MAX_MANIFEST_FILE_BYTES),
                "sha256": _digest(item["sha256"], "candidate manifest digest"),
            }
        )
    return result


def _validate_metrics(value: object) -> dict[str, float]:
    if not isinstance(value, dict) or len(value) > len(SAFE_DETAIL_METRIC_NAMES):
        raise FeedbackError("detail_metrics must be a bounded object")
    result: dict[str, float] = {}
    for key, metric in value.items():
        if not isinstance(key, str) or key not in SAFE_DETAIL_METRIC_NAMES:
            raise FeedbackError("detail_metrics contains an unsafe metric name")
        result[key] = _finite(metric, f"detail metric {key}")  # type: ignore[assignment]
    return result


def normalize_feedback(payload: object, *, expected_round: int | None = None) -> dict[str, object]:
    """Validate a full feedback object or normalize Feature 051's legacy score summary."""

    if not isinstance(payload, dict):
        raise FeedbackError("previous evaluation must be an object")
    legacy_fields = {"round_index", "validity_score", "overall_score", "quality_score"}
    if set(payload) == legacy_fields:
        round_index = _integer(payload["round_index"], "feedback round index", 1, 10_000)
        if expected_round is not None and round_index != expected_round:
            raise FeedbackError("previous evaluation round does not precede subject round")
        validity = _finite(payload["validity_score"], "feedback validity", nullable=True)
        overall = _finite(payload["overall_score"], "feedback overall", nullable=True)
        quality = _finite(payload["quality_score"], "feedback quality", nullable=True)
        return {
            "schema_version": "1",
            "round_index": round_index,
            "validity_score": validity,
            "overall_score": overall,
            "quality_score": quality,
            "score_delta": None,
            "best_overall_score": overall,
            "best_round_index": round_index if overall is not None and validity not in {None, 0.0} else None,
            "failure_category": "none" if overall is not None and validity not in {None, 0.0} else "score_unavailable",
            "detail_metrics": {},
            "candidate_manifest": [],
            "stagnation": {"detected": False, "consecutive_rounds": 0, "window": 2},
            "directive": "preserve_best_and_probe",
        }
    fields = {
        "schema_version",
        "round_index",
        "validity_score",
        "overall_score",
        "quality_score",
        "score_delta",
        "best_overall_score",
        "best_round_index",
        "failure_category",
        "detail_metrics",
        "candidate_manifest",
        "stagnation",
        "directive",
    }
    item = _strict_object(payload, fields, "round feedback")
    if item["schema_version"] != "1":
        raise FeedbackError("round feedback schema version is unsupported")
    round_index = _integer(item["round_index"], "feedback round index", 1, 10_000)
    if expected_round is not None and round_index != expected_round:
        raise FeedbackError("previous evaluation round does not precede subject round")
    validity = _finite(item["validity_score"], "feedback validity", nullable=True)
    overall = _finite(item["overall_score"], "feedback overall", nullable=True)
    quality = _finite(item["quality_score"], "feedback quality", nullable=True)
    delta = _finite(item["score_delta"], "feedback score delta", nullable=True)
    best = _finite(item["best_overall_score"], "feedback best score", nullable=True)
    best_round = item["best_round_index"]
    if best_round is not None:
        best_round = _integer(best_round, "feedback best round", 1, 10_000)
    failure = item["failure_category"]
    if failure not in FAILURE_CATEGORIES:
        raise FeedbackError("feedback failure category is unsupported")
    metrics = _validate_metrics(item["detail_metrics"])
    manifest = _validate_manifest(item["candidate_manifest"])
    stagnation = _strict_object(item["stagnation"], {"detected", "consecutive_rounds", "window"}, "feedback stagnation")
    if not isinstance(stagnation["detected"], bool):
        raise FeedbackError("feedback stagnation detected must be boolean")
    consecutive = _integer(stagnation["consecutive_rounds"], "feedback stagnation count", 0, 10_000)
    window = _integer(stagnation["window"], "feedback stagnation window", 1, MAX_STAGNATION_ROUNDS)
    if stagnation["detected"] != (consecutive >= window):
        raise FeedbackError("feedback stagnation flag disagrees with count")
    directive = item["directive"]
    if directive not in DIRECTIVES:
        raise FeedbackError("feedback directive is unsupported")
    normalized: dict[str, object] = {
        "schema_version": "1",
        "round_index": round_index,
        "validity_score": validity,
        "overall_score": overall,
        "quality_score": quality,
        "score_delta": delta,
        "best_overall_score": best,
        "best_round_index": best_round,
        "failure_category": failure,
        "detail_metrics": metrics,
        "candidate_manifest": manifest,
        "stagnation": {
            "detected": stagnation["detected"],
            "consecutive_rounds": consecutive,
            "window": window,
        },
        "directive": directive,
    }
    if len(str(normalized).encode("utf-8")) > MAX_FEEDBACK_BYTES:
        raise FeedbackError("round feedback exceeds its bounded size")
    return normalized


def build_candidate_manifest(root: str | Path) -> list[dict[str, object]]:
    """Return a deterministic hash-only projection of candidate artifacts."""

    workspace = Path(root).expanduser()
    if workspace.is_symlink() or not workspace.is_dir():
        raise FeedbackError("candidate workspace must be a regular directory")
    workspace = workspace.resolve()
    paths: list[Path] = []
    for current, directories, names in os.walk(workspace, topdown=True, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name
            for name in directories
            if name not in {"case", "receipts", "__pycache__"} and not (current_path / name).is_symlink()
        )
        for name in sorted(names):
            path = current_path / name
            if name == "request.json" or name.endswith(".pyc") or path.is_symlink() or not path.is_file():
                continue
            paths.append(path)
    result: list[dict[str, object]] = []
    for path in sorted(paths, key=lambda value: value.relative_to(workspace).as_posix().encode("utf-8"))[:MAX_MANIFEST_ENTRIES]:
        content = path.read_bytes()
        if len(content) > MAX_MANIFEST_FILE_BYTES:
            raise FeedbackError("candidate artifact exceeds manifest size bound")
        result.append(
            {
                "path": path.relative_to(workspace).as_posix(),
                "size_bytes": len(content),
                "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
            }
        )
    return result


def _scoreable(round_record: Mapping[str, object]) -> bool:
    return (
        round_record.get("extraction_status") == "completed"
        and round_record.get("validity_score") not in {None, 0.0}
        and round_record.get("overall_score") is not None
    )


def _failure_category(scored: Mapping[str, object]) -> str:
    if scored.get("extraction_status") != "completed":
        return "evaluation_failed"
    if scored.get("validity_score") in {None, 0.0}:
        return "invalid_candidate"
    if scored.get("overall_score") is None:
        return "score_unavailable"
    return "none"


def build_round_feedback(
    round_index: int,
    scored: Mapping[str, object],
    *,
    candidate_manifest: Iterable[Mapping[str, object]],
    prior_rounds: Sequence[Mapping[str, object]],
    stagnation_rounds: int = 2,
) -> dict[str, object]:
    """Create and validate the feedback projection sent to the next fresh subject."""

    round_index = _integer(round_index, "feedback round index", 1, 10_000)
    stagnation_rounds = _integer(stagnation_rounds, "feedback stagnation window", 1, MAX_STAGNATION_ROUNDS)
    current = {
        "round_index": round_index,
        "extraction_status": scored.get("extraction_status"),
        "validity_score": scored.get("validity_score"),
        "overall_score": scored.get("overall_score"),
        "quality_score": scored.get("quality_score"),
    }
    history = [*prior_rounds, current]
    prior_valid = [item for item in prior_rounds if _scoreable(item)]
    valid_history = [item for item in history if _scoreable(item)]
    previous_score = prior_rounds[-1].get("overall_score") if prior_rounds else None
    current_score = current["overall_score"] if _scoreable(current) else None
    score_delta = None
    if current_score is not None and isinstance(previous_score, (int, float)) and math.isfinite(previous_score):
        score_delta = float(current_score) - float(previous_score)
    prior_best = max((float(item["overall_score"]) for item in prior_valid), default=None)
    best_item = max(valid_history, key=lambda item: (float(item["overall_score"]), -int(item["round_index"])), default=None)
    best_score = float(best_item["overall_score"]) if best_item else None
    best_round = int(best_item["round_index"]) if best_item else None
    trailing = 0
    for index in range(len(history) - 1, -1, -1):
        item = history[index]
        if not _scoreable(item):
            trailing += 1
            continue
        item_score = float(item["overall_score"])
        earlier = [
            float(previous["overall_score"])
            for previous in history[:index]
            if _scoreable(previous)
        ]
        if not earlier or item_score > max(earlier):
            break
        trailing += 1
    detected = trailing >= stagnation_rounds
    failure = _failure_category(scored)
    if failure == "invalid_candidate":
        directive = "repair_validity"
    elif failure == "evaluation_failed":
        directive = "repair_evaluation"
    elif detected:
        directive = "change_search_strategy"
    elif current_score is not None and (prior_best is None or current_score > prior_best):
        directive = "refine_best"
    else:
        directive = "preserve_best_and_probe"
    filtered_metrics: dict[str, float] = {}
    details = scored.get("detail_metrics")
    if isinstance(details, Mapping):
        for key in sorted(SAFE_DETAIL_METRIC_NAMES):
            value = details.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                filtered_metrics[key] = float(value)
    manifest = [dict(value) for value in candidate_manifest]
    feedback = {
        "schema_version": "1",
        "round_index": round_index,
        "validity_score": _finite(current["validity_score"], "feedback validity", nullable=True),
        "overall_score": _finite(current["overall_score"], "feedback overall", nullable=True),
        "quality_score": _finite(current["quality_score"], "feedback quality", nullable=True),
        "score_delta": score_delta,
        "best_overall_score": best_score,
        "best_round_index": best_round,
        "failure_category": failure,
        "detail_metrics": filtered_metrics,
        "candidate_manifest": manifest,
        "stagnation": {"detected": detected, "consecutive_rounds": trailing, "window": stagnation_rounds},
        "directive": directive,
    }
    return normalize_feedback(feedback, expected_round=round_index)


__all__ = [
    "DIRECTIVES",
    "FAILURE_CATEGORIES",
    "MAX_FEEDBACK_BYTES",
    "MAX_MANIFEST_ENTRIES",
    "SAFE_DETAIL_METRIC_NAMES",
    "FeedbackError",
    "build_candidate_manifest",
    "build_round_feedback",
    "normalize_feedback",
]
