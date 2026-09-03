"""Reproducible local comparisons over Lunar-Agent evolution strategies.

The benchmark layer only orchestrates existing ``EvolutionContext`` implementations. It does not
change candidate ranking, evaluator authority, or the durable SQLite controller.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .algorithm import AlgorithmProblemContract
from .evolution import (
    CandidateEvaluator,
    CandidateGenerator,
    EvolutionConfig,
    EvolutionContext,
    StrategyResult,
    build_strategy,
)

BENCHMARK_STRATEGIES = ("loop", "population", "openevolve")
MAX_BENCHMARK_STRATEGIES = 3
MAX_REPORT_BYTES = 64 * 1024
MAX_ERROR_BYTES = 2_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STATUSES = {"completed", "stagnated", "failed", "cancelled"}


def _bounded_error(value: object) -> str:
    text = " ".join(str(value).split())
    return text[-MAX_ERROR_BYTES:] if text else "benchmark strategy failed"


def _relative(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise BenchmarkError(f"{field_name} must be a relative path")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BenchmarkError(f"{field_name} must be a relative path")
    return path.as_posix()


class BenchmarkError(ValueError):
    """A benchmark configuration or report boundary is invalid."""


@dataclass(frozen=True)
class BenchmarkConfig:
    """Common bounded settings applied to every selected native strategy."""

    strategies: tuple[str, ...] = ("loop", "population")
    max_rounds: int = 5
    stagnation_rounds: int = 3
    population_size: int = 8
    offspring_per_iteration: int = 1
    num_islands: int = 1
    migration_interval: int = 0
    migration_rate: float = 0.1
    rng_seed: int | None = None
    timeout_seconds: float = 900.0
    generator_fingerprint: str | None = None
    evaluator_fingerprint: str | None = None
    strategy_commands: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.strategies, (str, bytes)):
            raise BenchmarkError("strategies must be a non-empty sequence")
        normalized = tuple(self.strategies)
        if not 1 <= len(normalized) <= MAX_BENCHMARK_STRATEGIES:
            raise BenchmarkError("benchmark requires at least one and at most three strategies")
        if any(strategy not in BENCHMARK_STRATEGIES for strategy in normalized):
            raise BenchmarkError(
                "benchmark strategy is unsupported; choose loop, population, or openevolve"
            )
        if len(set(normalized)) != len(normalized):
            raise BenchmarkError("benchmark strategies must be unique")
        object.__setattr__(self, "strategies", normalized)
        if not isinstance(self.strategy_commands, dict):
            raise BenchmarkError("strategy_commands must be an object")
        normalized_commands: dict[str, tuple[str, ...]] = {}
        for strategy, command in self.strategy_commands.items():
            if strategy not in normalized:
                raise BenchmarkError(f"command configured for unselected strategy {strategy!r}")
            if isinstance(command, (str, bytes)):
                raise BenchmarkError("strategy command must be a bounded argument sequence")
            command_tuple = tuple(command)
            if not command_tuple or len(command_tuple) > 32 or any(
                not isinstance(item, str) or not item for item in command_tuple
            ):
                raise BenchmarkError("strategy command must be a bounded argument sequence")
            normalized_commands[strategy] = command_tuple
        if "openevolve" in normalized and not normalized_commands.get("openevolve"):
            raise BenchmarkError("openevolve strategy requires an explicit command")
        object.__setattr__(self, "strategy_commands", normalized_commands)
        for strategy in normalized:
            EvolutionConfig(
                strategy=strategy,  # type: ignore[arg-type]
                max_rounds=self.max_rounds,
                stagnation_rounds=self.stagnation_rounds,
                population_size=self.population_size,
                offspring_per_iteration=self.offspring_per_iteration,
                num_islands=self.num_islands,
                migration_interval=self.migration_interval,
                migration_rate=self.migration_rate,
                rng_seed=self.rng_seed,
                timeout_seconds=self.timeout_seconds,
                command=normalized_commands.get(strategy, ()),
            )
        for name, fingerprint in (
            ("generator_fingerprint", self.generator_fingerprint),
            ("evaluator_fingerprint", self.evaluator_fingerprint),
        ):
            if fingerprint is not None and (
                not isinstance(fingerprint, str) or not _SHA256.fullmatch(fingerprint)
            ):
                raise BenchmarkError(f"{name} must be a lowercase SHA-256 hex digest or null")

    def evolution(self, strategy: str) -> EvolutionConfig:
        if strategy not in self.strategies:
            raise BenchmarkError(f"strategy {strategy!r} is not selected for this benchmark")
        return EvolutionConfig(
            strategy=strategy,  # type: ignore[arg-type]
            max_rounds=self.max_rounds,
            stagnation_rounds=self.stagnation_rounds,
            population_size=self.population_size,
            offspring_per_iteration=self.offspring_per_iteration,
            num_islands=self.num_islands,
            migration_interval=self.migration_interval,
            migration_rate=self.migration_rate,
            rng_seed=self.rng_seed,
            timeout_seconds=self.timeout_seconds,
            generator_fingerprint=self.generator_fingerprint,
            evaluator_fingerprint=self.evaluator_fingerprint,
            command=self.strategy_commands.get(strategy, ()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategies": list(self.strategies),
            "max_rounds": self.max_rounds,
            "stagnation_rounds": self.stagnation_rounds,
            "population_size": self.population_size,
            "offspring_per_iteration": self.offspring_per_iteration,
            "num_islands": self.num_islands,
            "migration_interval": self.migration_interval,
            "migration_rate": self.migration_rate,
            "rng_seed": self.rng_seed,
            "timeout_seconds": self.timeout_seconds,
            "generator_fingerprint": self.generator_fingerprint,
            "evaluator_fingerprint": self.evaluator_fingerprint,
            "strategy_commands_sha256": {
                strategy: hashlib.sha256(
                    json.dumps(list(command), ensure_ascii=False, separators=(",", ":")).encode(
                        "utf-8"
                    )
                ).hexdigest()
                for strategy, command in self.strategy_commands.items()
            },
        }


@dataclass(frozen=True)
class BenchmarkRun:
    """One strategy's bounded result projection."""

    strategy: Literal["loop", "population", "openevolve"]
    status: Literal["completed", "stagnated", "failed", "cancelled"]
    elapsed_ms: int
    evaluated_candidates: int
    valid_candidates: int
    best_score: float | None
    workspace: str
    archive: str
    error: str | None = None
    best_candidate_path: str | None = None

    def __post_init__(self) -> None:
        if self.strategy not in BENCHMARK_STRATEGIES:
            raise BenchmarkError("benchmark run strategy is unsupported")
        if self.status not in _STATUSES:
            raise BenchmarkError("benchmark run status is unsupported")
        if (
            isinstance(self.elapsed_ms, bool)
            or not isinstance(self.elapsed_ms, int)
            or not 0 <= self.elapsed_ms <= 86_400_000
        ):
            raise BenchmarkError("benchmark elapsed_ms is out of bounds")
        for name, value in (
            ("evaluated_candidates", self.evaluated_candidates),
            ("valid_candidates", self.valid_candidates),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10_000_000:
                raise BenchmarkError(f"benchmark {name} is out of bounds")
        if self.valid_candidates > self.evaluated_candidates:
            raise BenchmarkError("valid_candidates cannot exceed evaluated_candidates")
        if self.best_score is not None and (
            isinstance(self.best_score, bool)
            or not isinstance(self.best_score, (int, float))
            or not math.isfinite(float(self.best_score))
        ):
            raise BenchmarkError("benchmark best_score must be finite or null")
        _relative(self.workspace, "benchmark workspace")
        _relative(self.archive, "benchmark archive")
        if self.best_candidate_path is not None:
            _relative(self.best_candidate_path, "benchmark best candidate path")
        if self.error is not None:
            if not isinstance(self.error, str):
                raise BenchmarkError("benchmark error must be text or null")
            object.__setattr__(self, "error", _bounded_error(self.error))

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "status": self.status,
            "elapsed_ms": self.elapsed_ms,
            "evaluated_candidates": self.evaluated_candidates,
            "valid_candidates": self.valid_candidates,
            "best_score": self.best_score,
            "best_candidate_path": self.best_candidate_path,
            "workspace": self.workspace,
            "archive": self.archive,
            "error": self.error,
        }


@dataclass(frozen=True)
class BenchmarkReport:
    """JSON-safe report for one immutable contract and selected strategies."""

    contract_sha256: str
    config: BenchmarkConfig
    runs: tuple[BenchmarkRun, ...]

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.contract_sha256):
            raise BenchmarkError("contract_sha256 must be a lowercase SHA-256 hex digest")
        if not isinstance(self.config, BenchmarkConfig):
            raise TypeError("benchmark config must be a BenchmarkConfig")
        if tuple(item.strategy for item in self.runs) != self.config.strategies:
            raise BenchmarkError("benchmark runs must match the selected strategy order")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "contract_sha256": self.contract_sha256,
            "config": self.config.to_dict(),
            "runs": [item.to_dict() for item in self.runs],
        }


GeneratorFactory = Callable[[str], CandidateGenerator]
EvaluatorFactory = Callable[[str], CandidateEvaluator]


class BenchmarkRunner:
    """Run each selected native strategy in a fresh local workspace."""

    def __init__(
        self,
        contract: AlgorithmProblemContract,
        workspace: str | Path,
        *,
        generator_factory: GeneratorFactory,
        evaluator_factory: EvaluatorFactory,
        config: BenchmarkConfig | None = None,
    ) -> None:
        if not isinstance(contract, AlgorithmProblemContract):
            raise TypeError("contract must be an AlgorithmProblemContract")
        if not callable(generator_factory) or not callable(evaluator_factory):
            raise TypeError("benchmark generator/evaluator factories must be callable")
        self.contract = contract
        self.workspace = Path(workspace).expanduser().resolve(strict=False)
        self.config = config or BenchmarkConfig()
        self.generator_factory = generator_factory
        self.evaluator_factory = evaluator_factory
        self._started = False
        if self.workspace.exists():
            if self.workspace.is_symlink():
                raise BenchmarkError("benchmark workspace must not be a symlink")
            if not self.workspace.is_dir():
                raise BenchmarkError("benchmark workspace must be a directory")
            if any(self.workspace.iterdir()):
                raise BenchmarkError("benchmark workspace is not empty; refusing to overwrite")

    def run(self) -> BenchmarkReport:
        if self._started:
            raise BenchmarkError("benchmark runner can only be run once")
        self._started = True
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._write_contract()
        runs: list[BenchmarkRun] = []
        for strategy in self.config.strategies:
            runs.append(self._run_strategy(strategy))
        report = BenchmarkReport(self.contract.digest(), self.config, tuple(runs))
        encoded = json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if len(encoded.encode("utf-8")) > MAX_REPORT_BYTES:
            raise BenchmarkError("benchmark report exceeds the bounded size")
        report_path = self.workspace / "benchmark.json"
        if report_path.exists() and report_path.is_symlink():
            raise BenchmarkError("benchmark report must not be a symlink")
        temporary = self.workspace / ".benchmark.json.tmp"
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(report_path)
        return report

    def _write_contract(self) -> None:
        path = self.workspace / "contract.json"
        if path.exists() and path.is_symlink():
            raise BenchmarkError("benchmark contract must not be a symlink")
        path.write_text(
            json.dumps(self.contract.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def _run_strategy(self, strategy: str) -> BenchmarkRun:
        strategy_root = self.workspace / "strategies" / strategy
        if strategy_root.exists() and strategy_root.is_symlink():
            raise BenchmarkError("strategy workspace must not be a symlink")
        strategy_root.mkdir(parents=True, exist_ok=True)
        contract_path = strategy_root / "evolution" / "contract.json"
        contract_path.parent.mkdir(parents=True, exist_ok=True)
        contract_path.write_text(
            json.dumps(self.contract.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        started = time.monotonic()
        default_archive = f"strategies/{strategy}/evolution/archive.jsonl"
        try:
            generator = self.generator_factory(strategy)
            evaluator = self.evaluator_factory(strategy)
            if not callable(generator) or not callable(evaluator):
                raise BenchmarkError("benchmark factories must return callable generator/evaluator")
            context = EvolutionContext(
                contract=self.contract,
                workspace=strategy_root,
                generate=generator,
                evaluate=evaluator,
                config=self.config.evolution(strategy),
            )
            result = build_strategy(context).run()
            return self._project(strategy, result, started, strategy_root, default_archive)
        except Exception as exc:  # noqa: BLE001 - isolate one strategy from the benchmark set
            return BenchmarkRun(
                strategy=strategy,  # type: ignore[arg-type]
                status="failed",
                elapsed_ms=self._elapsed(started),
                evaluated_candidates=0,
                valid_candidates=0,
                best_score=None,
                workspace=f"strategies/{strategy}",
                archive=default_archive,
                error=_bounded_error(exc),
            )

    @staticmethod
    def _elapsed(started: float) -> int:
        return min(86_400_000, max(0, int((time.monotonic() - started) * 1000)))

    def _project(
        self,
        strategy: str,
        result: StrategyResult,
        started: float,
        strategy_root: Path,
        default_archive: str,
    ) -> BenchmarkRun:
        if result.strategy != strategy:
            raise BenchmarkError("strategy returned a mismatched result")
        archive = (strategy_root / result.archive_path).resolve(strict=False)
        try:
            archive_rel = archive.relative_to(self.workspace).as_posix()
        except ValueError as exc:
            raise BenchmarkError("strategy archive escapes benchmark workspace") from exc
        best_path = None
        if result.best_candidate_path is not None:
            candidate = (strategy_root / result.best_candidate_path).resolve(strict=False)
            try:
                best_path = candidate.relative_to(self.workspace).as_posix()
            except ValueError as exc:
                raise BenchmarkError("strategy best candidate escapes benchmark workspace") from exc
        return BenchmarkRun(
            strategy=strategy,  # type: ignore[arg-type]
            status=result.status,  # type: ignore[arg-type]
            elapsed_ms=self._elapsed(started),
            evaluated_candidates=result.evaluated_candidates,
            valid_candidates=result.valid_candidates,
            best_score=result.best_score,
            workspace=f"strategies/{strategy}",
            archive=archive_rel or default_archive,
            error=result.error,
            best_candidate_path=best_path,
        )


__all__ = [
    "BENCHMARK_STRATEGIES",
    "BenchmarkConfig",
    "BenchmarkError",
    "BenchmarkReport",
    "BenchmarkRun",
    "BenchmarkRunner",
]
