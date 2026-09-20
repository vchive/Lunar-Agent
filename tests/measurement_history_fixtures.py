"""Portable unit fixtures for sealed-history validation, not private campaign inventories.

The tracked seal is checked against its unchanged registered SHA values first. Its predecessor
path set then shapes an explicitly synthetic temporary chain. Only fixture seal constants are
rebound; the historical byte readers, digest checks, and history algorithm remain unchanged.
"""

import json


def prepare_history_fixture(audit, repo, fixture_root, monkeypatch):
    registered_seal = dict(audit.SEALED_HISTORY)
    assert all(relative.startswith("specs/") for relative in registered_seal)
    audit.check_map(repo, registered_seal)
    manifest_relative = audit.PRIOR_ROOT + "/measurement/manifest.json"
    final_relative = audit.PRIOR_ROOT + "/postrun/final-audit.json"
    predecessor = audit.read(repo / manifest_relative)["historical_files_sha256"]
    assert isinstance(predecessor, dict) and predecessor
    assert set(predecessor).isdisjoint(registered_seal)

    for relative in set(predecessor) | set(registered_seal):
        path = audit.confined(fixture_root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"synthetic_history_fixture": relative}), encoding="utf-8")
    manifest_path = fixture_root / manifest_relative
    manifest_path.write_text(json.dumps({
        "synthetic_history_fixture": True,
        "historical_files_sha256": {
            relative: audit.sha(fixture_root / relative) for relative in predecessor
        },
    }), encoding="utf-8")
    (fixture_root / final_relative).write_text(json.dumps({
        "synthetic_history_fixture": True,
        "passed": True,
        "complete": True,
        "final_acceptance": True,
        "manifest_sha256": audit.sha(manifest_path),
    }), encoding="utf-8")
    monkeypatch.setattr(audit, "SEALED_HISTORY", {
        relative: audit.sha(fixture_root / relative) for relative in registered_seal
    })
    return fixture_root
