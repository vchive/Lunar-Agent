"""Stable synthetic inputs used by Feature 139's offline fixtures."""
from __future__ import annotations

import hashlib
import json

REGISTRATION_ID = "registration-139-real-multifile-closure"
CAMPAIGN_ID = "campaign-139-real-multifile-closure-20260919"
ATTEMPT_ID = "attempt-001"
CAMPAIGN_ROOT = ".lunar/real-automatic-multifile-closure-20260919"
# This is the product revision immediately after Feature 138.  The eventual
# registration remains a separate later commit that pins this product tree.
PRODUCT_COMMIT = "640e14a0e31074998f11e3b0e6421301ec5c61f3"
MODEL = "glm-5.2"
TASK_BYTES = b"feature-139-offline-task-v1\n"
INPUT_BYTES = b'{"limit":3}\n'


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def default_holdouts() -> list[dict[str, object]]:
    """Return eight independent, deterministic holdout expectations."""
    rows = []
    for index, (limit, value) in enumerate(
        ((1, 0), (1, 1), (1, 2), (2, 0), (2, 1), (2, 2), (3, 0), (3, 3)),
        start=1,
    ):
        rows.append({"index": index, "limit": limit, "expected_value": value})
    return rows


def expected_input_digest() -> str:
    return sha256(INPUT_BYTES)


def expected_task_digest() -> str:
    return sha256(TASK_BYTES)


def synthetic_source() -> dict[str, str]:
    """A valid source bundle used only as digest material in tests."""
    return {
        "solve/main.py": "from pathlib import Path\nPath('output').mkdir(exist_ok=True)\n",
        "solve/helper.py": "def choose(limit):\n    return limit\n",
    }


def synthetic_output() -> bytes:
    return json.dumps({"value": 3}, sort_keys=True, separators=(",", ":")).encode()
