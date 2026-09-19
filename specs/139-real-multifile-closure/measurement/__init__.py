"""Provider-free fixtures for the Feature 139 measurement contract.

The real run, if authorized later, may use the native automatic path.  These
helpers deliberately contain no runtime/provider imports and are only an
offline acceptance model for registration, receipts, and public reporting.
"""

from .campaign import (
    STAGE_ORDER,
    CampaignError,
    ClosureCampaign,
    RegistrationError,
    RequestLedger,
    default_manifest,
    validate_registration,
)

__all__ = [
    "STAGE_ORDER",
    "CampaignError",
    "ClosureCampaign",
    "RegistrationError",
    "RequestLedger",
    "default_manifest",
    "validate_registration",
]
