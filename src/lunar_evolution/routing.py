"""Deterministic, runtime-neutral domain routing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .budget import BudgetSpec

MAX_TEXT_BYTES = 8_000
MAX_ITEMS = 16
_SECRET_RE = re.compile(r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|api[_-]?key\s*[:=]\s*\S+)")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    value = value.strip()
    if len(value.encode("utf-8")) > MAX_TEXT_BYTES or _SECRET_RE.search(value):
        raise ValueError(f"{name} is too large or contains credential-like content")
    return value


@dataclass(frozen=True)
class RouteDecision:
    domain: str
    reason: str
    confidence: float
    required_capabilities: tuple[str, ...]
    solver_profile: str
    evaluator_profile: str
    budget: BudgetSpec
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.domain, "domain")
        _text(self.reason, "route reason")
        if not 0 <= self.confidence <= 1:
            raise ValueError("route confidence must be between 0 and 1")
        _text(self.solver_profile, "solver profile")
        _text(self.evaluator_profile, "evaluator profile")
        if len(self.required_capabilities) > MAX_ITEMS or len(self.evidence) > MAX_ITEMS:
            raise ValueError("route arrays are too large")
        for item in (*self.required_capabilities, *self.evidence):
            _text(item, "route item")

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "reason": self.reason,
            "confidence": self.confidence,
            "required_capabilities": list(self.required_capabilities),
            "solver_profile": self.solver_profile,
            "evaluator_profile": self.evaluator_profile,
            "budget": self.budget.to_dict(),
            "evidence": list(self.evidence),
        }


class DomainRouter:
    """Small deterministic router; model-assisted routing can implement this same contract later."""

    _signals = (
        ("coding", ("code", "coding", "bug", "debug", "test", "pytest", "repository", "代码", "开发", "测试", "修复")),
        ("data", ("csv", "spreadsheet", "excel", "sql", "dataset", "dataframe", "数据", "表格", "聚合", "统计")),
        ("research", ("research", "literature", "sources", "citations", "paper", "调查", "研究", "文献", "引用")),
    )

    def route(self, goal: str) -> RouteDecision:
        goal = _text(goal, "goal")
        lowered = goal.lower()
        matches: list[tuple[str, str]] = []
        for domain, signals in self._signals:
            for signal in signals:
                matched = (
                    bool(re.search(rf"(?<![a-z0-9_]){re.escape(signal.lower())}(?![a-z0-9_])", lowered))
                    if signal.isascii() and signal.isalpha()
                    else signal.lower() in lowered
                )
                if matched:
                    matches.append((domain, signal))
        if not matches:
            return RouteDecision(
                "general", "no domain-specific signal detected", 0.62,
                ("read_files", "write_artifacts"), "general", "general", BudgetSpec(),
                ("fallback:general",),
            )
        # Stable precedence avoids model-like nondeterminism when a goal spans domains.
        domain = next(item[0] for item in self._signals if any(match[0] == item[0] for match in matches))
        evidence = tuple(f"signal:{signal}" for matched_domain, signal in matches if matched_domain == domain)[:MAX_ITEMS]
        confidence = min(0.95, 0.78 + 0.04 * (len(evidence) - 1))
        capabilities = {
            "coding": ("read_files", "write_files", "run_tests", "write_artifacts"),
            "data": ("read_files", "write_files", "analyze_data", "write_artifacts"),
            "research": ("read_files", "gather_sources", "write_artifacts"),
        }[domain]
        return RouteDecision(domain, f"matched {domain} goal signals", confidence, capabilities, domain, domain, BudgetSpec(), evidence)
