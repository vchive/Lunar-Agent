"""Private reuse of the pinned loader and validators for exactly two new staged attempts."""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CAMPAIGN_ID = "real-eval-glm-5.2-corrected-staged-20260910"
CAMPAIGN = REPO / ".lunar" / CAMPAIGN_ID
IMPLEMENTATION = "c28e498e539b3ed6e37d743145ba1c38f9b1e9e2"
ORDER = [("master_1200", "sheet_metal_nesting"), ("master_1200", "china_post_pickup_optimization")]
POLICIES = {"master_1200": {"master_seconds": 1200, "build_seconds": 2400,
                             "reserve_seconds": 120, "checkpoint_after_rounds": 32}}
EXECUTION = {"waves": [[1, 2]], "concurrency": 2, "subject_outer_seconds": 5430,
             "harness_outer_seconds": 3630, "slot_outer_seconds": 9300}
PRIOR_ROOT = REPO / "specs/072-master-budget-measurement"
PRIOR_FILES = {
    "measurement/adapter.py": "40b4eb91afe4e99b61e40168347024b86f786817d13c4b2c15743c4f2fa21826",
    "measurement/audit.py": "84f722639d793bfc0f1a7bee829120a4390c8ce0d1b36ee270569bce0da0bb7f",
    "measurement/prepare.py": "c5482a0c9499ef9a391e5b554b327dbd8424255ce6adc6bfc7b249af2192ff35",
    "measurement/dry_run.py": "e67c93aa0c574657c5aeda5289f473ab08268e9450785dfca07e376c4b56aace",
    "postrun/audit.py": "6e060bbbb60754bd38696bed75f57dd9a0ca95f2d3a2487875c72d709739c307",
}


def _load_prior(relative, *, overrides=None):
    if relative not in PRIOR_FILES:
        raise ValueError("unknown pinned measurement helper")
    path = PRIOR_ROOT / relative
    if path.is_symlink() or not path.is_file() or path.resolve() != path:
        raise ValueError("unsafe pinned measurement helper")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PRIOR_FILES[relative]:
        raise ValueError("pinned measurement helper changed")
    module = ModuleType("_feature074_prior_" + relative.replace("/", "_"))
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec"), module.__dict__)  # noqa: S102 - pinned trusted repository code
    module.__dict__.update(overrides or {})
    return module


def load_prior(name, *, overrides=None):
    return _load_prior(f"measurement/{name}.py", overrides=overrides)


def load_prior_postrun():
    return _load_prior("postrun/audit.py")


# Configure one private loader instance. Its import map loads current wrappers from HERE without
# inserting prepare/worker aliases into sys.modules; the original 069/072 files remain immutable.
_loader = load_prior("adapter")
for _name in ("REPO", "HERE", "CAMPAIGN_ID", "CAMPAIGN", "IMPLEMENTATION", "ORDER", "POLICIES", "EXECUTION"):
    setattr(_loader, _name, globals()[_name])
_loader.load_prior = load_prior
_loader.load_prior_postrun = load_prior_postrun
_loader.PRIOR_ROOT, _loader.PRIOR_FILES = PRIOR_ROOT, PRIOR_FILES
LEGACY_ROOT, LEGACY_FILES = _loader.LEGACY_ROOT, _loader.LEGACY_FILES
HELPER_FILES = {
    **{(LEGACY_ROOT / name).relative_to(REPO).as_posix(): digest for name, digest in LEGACY_FILES.items()},
    **{(PRIOR_ROOT / name).relative_to(REPO).as_posix(): digest for name, digest in PRIOR_FILES.items()},
}
_loader.HELPER_FILES = HELPER_FILES
load_legacy, load_current = _loader.load_legacy, _loader.load_current
load_worker, load_campaign = _loader.load_worker, _loader.load_campaign
