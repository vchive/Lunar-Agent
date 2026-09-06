"""Deterministic token and cost accounting for model profiles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .budget import BudgetExceeded
from .profiles import ModelProfile


@dataclass(frozen=True)
class UsageSnapshot:
    """Aggregate usage observed by a ledger."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_micros: int | None
    rounds: int

    def to_dict(self) -> dict[str, int | None]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_micros": self.cost_micros,
            "rounds": self.rounds,
        }


class UsageLedger:
    """Account normalized runtime usage and enforce profile ceilings before commit."""

    def __init__(self, profile: ModelProfile) -> None:
        if not isinstance(profile, ModelProfile):
            raise TypeError("profile must be a ModelProfile")
        self.profile = profile
        self._input_tokens = 0
        self._output_tokens = 0
        self._rounds = 0

    @property
    def snapshot(self) -> UsageSnapshot:
        return UsageSnapshot(
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            total_tokens=self._input_tokens + self._output_tokens,
            cost_micros=self._cost(self._input_tokens, self._output_tokens),
            rounds=self._rounds,
        )

    def record(self, usage: Mapping[str, object]) -> UsageSnapshot:
        """Record one normalized ``input_tokens/output_tokens/total_tokens`` sample.

        The counters are unchanged when a sample is malformed or would exceed a configured
        ceiling.  This makes it safe for callers to turn a ``BudgetExceeded`` into a bounded
        round failure without accidentally charging the rejected sample.
        """

        if not isinstance(usage, Mapping):
            raise TypeError("usage must be an object")
        required = {"input_tokens", "output_tokens", "total_tokens"}
        if set(usage) != required:
            raise ValueError("usage must contain input_tokens, output_tokens, and total_tokens")
        values: dict[str, int] = {}
        for name in required:
            value = usage[name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"usage {name} must be a non-negative integer")
            values[name] = value
        if values["input_tokens"] + values["output_tokens"] != values["total_tokens"]:
            raise ValueError("usage total must equal input plus output")
        new_input = self._input_tokens + values["input_tokens"]
        new_output = self._output_tokens + values["output_tokens"]
        new_total = new_input + new_output
        if self.profile.max_total_tokens is not None and new_total > self.profile.max_total_tokens:
            raise BudgetExceeded("max_total_tokens", new_total, self.profile.max_total_tokens)
        new_cost = self._cost(new_input, new_output)
        if (
            self.profile.max_cost_micros is not None
            and new_cost is not None
            and new_cost > self.profile.max_cost_micros
        ):
            raise BudgetExceeded("max_cost_micros", new_cost, self.profile.max_cost_micros)
        self._input_tokens, self._output_tokens = new_input, new_output
        self._rounds += 1
        return self.snapshot

    def _cost(self, input_tokens: int, output_tokens: int) -> int | None:
        input_rate = self.profile.input_cost_per_1k_micros
        output_rate = self.profile.output_cost_per_1k_micros
        if input_rate is None or output_rate is None:
            return None
        # Charge each direction independently and round up fractional token blocks.  All values
        # remain integer micro-USD, avoiding floating point drift in persisted reports.
        return (
            (input_tokens * input_rate + 999) // 1_000
            + (output_tokens * output_rate + 999) // 1_000
        )


__all__ = ["UsageLedger", "UsageSnapshot"]
