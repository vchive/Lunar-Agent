import pytest

from famou.budget import BudgetExceeded
from famou.model_profile import UsageLedger
from famou.profiles import ModelProfile


def test_model_profile_round_trips_and_ledger_reports_cost() -> None:
    profile = ModelProfile(
        "cheap-local",
        "fixture-model",
        thinking_budget=256,
        max_steps=8,
        timeout_seconds=12,
        max_total_tokens=100,
        max_cost_micros=500,
        input_cost_per_1k_micros=1_000,
        output_cost_per_1k_micros=2_000,
    )
    assert ModelProfile.from_dict(profile.to_dict()) == profile
    ledger = UsageLedger(profile)
    snapshot = ledger.record({"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    assert snapshot.to_dict() == {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
        "cost_micros": 20,
        "rounds": 1,
    }


def test_model_profile_from_dict_requires_identity() -> None:
    with pytest.raises(ValueError, match="required fields"):
        ModelProfile.from_dict({"max_steps": 2})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"thinking_budget": -1},
        {"max_steps": 0},
        {"timeout_seconds": 0},
        {"max_total_tokens": 0},
        {"input_cost_per_1k_micros": 1},
        {"max_cost_micros": 1},
        {"model": "sk-this-must-not-look-like-a-secret"},
    ],
)
def test_model_profile_rejects_unsafe_or_unbounded_values(kwargs: dict[str, object]) -> None:
    with pytest.raises((ValueError, TypeError)):
        ModelProfile("test", "local", **kwargs)


def test_usage_ledger_rejects_malformed_usage_without_charging() -> None:
    ledger = UsageLedger(ModelProfile("test", "local", max_total_tokens=10))
    with pytest.raises(ValueError, match="total"):
        ledger.record({"input_tokens": 2, "output_tokens": 2, "total_tokens": 9})
    assert ledger.snapshot.total_tokens == 0


def test_usage_ledger_enforces_token_and_cost_ceilings() -> None:
    token_limited = UsageLedger(ModelProfile("token", "local", max_total_tokens=5))
    token_limited.record({"input_tokens": 2, "output_tokens": 2, "total_tokens": 4})
    with pytest.raises(BudgetExceeded, match="max_total_tokens"):
        token_limited.record({"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
    assert token_limited.snapshot.total_tokens == 4

    cost_limited = UsageLedger(
        ModelProfile(
            "cost", "local", max_cost_micros=2,
            input_cost_per_1k_micros=1_000, output_cost_per_1k_micros=1_000,
        )
    )
    with pytest.raises(BudgetExceeded, match="max_cost_micros"):
        cost_limited.record({"input_tokens": 1, "output_tokens": 2, "total_tokens": 3})
    assert cost_limited.snapshot.rounds == 0
