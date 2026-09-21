"""Deterministic token and cost accounting for model profiles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

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


@dataclass(frozen=True)
class BudgetFailureEvidence:
    """Failure-local reported usage; never a claim of complete provider consumption.

    ``accepted_usage`` is the ledger at failure. ``observed_usage`` additionally includes a
    rejected triggering response, or equals the accepted ledger when that response exhausted
    the ceiling exactly. Diagnostic projection applies its own bounds without changing these
    execution values.
    """

    limit: Literal["max_total_tokens", "max_cost_micros"]
    state: Literal["exceeded", "exhausted"]
    maximum: int
    accepted_usage: UsageSnapshot
    observed_usage: UsageSnapshot
    trigger_recorded: bool


class ProfileBudgetExceeded(BudgetExceeded):
    """A profile ceiling rejection with immutable accepted and observed usage."""

    def __init__(self, evidence: BudgetFailureEvidence) -> None:
        self.evidence = evidence
        actual = (
            evidence.observed_usage.total_tokens
            if evidence.limit == "max_total_tokens" else evidence.observed_usage.cost_micros
        )
        if actual is None:
            raise ValueError("profile budget failure requires an observed limit value")
        super().__init__(evidence.limit, actual, evidence.maximum)


class UsageLedger:
    """Account normalized runtime usage and enforce profile ceilings before commit."""

    def __init__(self, profile: ModelProfile) -> None:
        if not isinstance(profile, ModelProfile):
            raise TypeError("profile must be a ModelProfile")
        self.profile = profile
        self._input_tokens = 0
        self._output_tokens = 0
        self._rounds = 0
        self._budget_failure: BudgetFailureEvidence | None = None
        self._usage_complete = True
        self._response_models: list[str | None] = []

    @property
    def usage_complete(self) -> bool:
        """Whether accepted counters cover every observed provider request."""
        return self._usage_complete and self._budget_failure is None

    @property
    def response_model(self) -> str | None:
        """A model identity only when all observed responses supplied the same value."""
        if (
            self._response_models
            and len(self._response_models) == self._rounds
            and all(self._response_models)
            and len(set(self._response_models)) == 1
        ):
            return self._response_models[0]
        return None

    def observe_response_model(self, model: str | None) -> None:
        self._response_models.append(model)

    def mark_usage_unavailable(self) -> None:
        """Latch uncertain consumption; subsequent samples cannot fill the missing turn."""
        self._usage_complete = False

    def check_request(self, *, require_complete: bool = True) -> None:
        """Refuse further provider spending after rejection, exhaustion, or unknown usage."""
        if self._budget_failure is not None:
            raise ProfileBudgetExceeded(self._budget_failure)
        if require_complete and not self._usage_complete:
            raise ValueError("model profile aggregate usage is unavailable")
        snapshot = self.snapshot
        for name, actual, maximum in (
            ("max_total_tokens", snapshot.total_tokens, self.profile.max_total_tokens),
            ("max_cost_micros", snapshot.cost_micros, self.profile.max_cost_micros),
        ):
            if maximum is not None and actual is not None and actual >= maximum:
                raise ProfileBudgetExceeded(BudgetFailureEvidence(
                    limit=name, state="exhausted", maximum=maximum,
                    accepted_usage=snapshot, observed_usage=snapshot, trigger_recorded=True,
                ))

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
        ceiling. A budget rejection reports the observed response separately from the accepted
        ledger; rejection does not imply that the provider did not charge for that response.
        """

        if self._budget_failure is not None:
            raise ProfileBudgetExceeded(self._budget_failure)
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
        new_cost = self._cost(new_input, new_output)
        accepted = self.snapshot
        observed = UsageSnapshot(new_input, new_output, new_total, new_cost, self._rounds + 1)
        if self.profile.max_total_tokens is not None and new_total > self.profile.max_total_tokens:
            self._budget_failure = BudgetFailureEvidence(
                limit="max_total_tokens", state="exceeded", maximum=self.profile.max_total_tokens,
                accepted_usage=accepted, observed_usage=observed, trigger_recorded=False,
            )
            raise ProfileBudgetExceeded(self._budget_failure)
        if (
            self.profile.max_cost_micros is not None
            and new_cost is not None
            and new_cost > self.profile.max_cost_micros
        ):
            self._budget_failure = BudgetFailureEvidence(
                limit="max_cost_micros", state="exceeded", maximum=self.profile.max_cost_micros,
                accepted_usage=accepted, observed_usage=observed, trigger_recorded=False,
            )
            raise ProfileBudgetExceeded(self._budget_failure)
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


__all__ = ["BudgetFailureEvidence", "ProfileBudgetExceeded", "UsageLedger", "UsageSnapshot"]
