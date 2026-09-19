"""Read-only audit and safe public projection for Feature 139 fixtures."""
from __future__ import annotations

from .campaign import CampaignError, ClosureCampaign


def audit(campaign: ClosureCampaign) -> dict:
    """Audit retained evidence without invoking a provider or executing source."""
    return campaign.audit()


def public_result(campaign: ClosureCampaign) -> dict:
    return campaign.public_result()


def assert_public_safe(result: dict) -> None:
    """Fail closed if private transport/source fields appear in a projection."""
    forbidden = ("prompt", "response", "credential", "endpoint", "url", "exception", "source")
    serialized = repr(result).lower()
    if any(token in serialized for token in forbidden):
        raise CampaignError("unsafe_public_projection")
