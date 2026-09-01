from pathlib import Path

from famou.memory import MemoryStore


def test_memory_store_round_trip_and_scoped_recall(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "state.db")
    memory.initialize()
    global_entry = memory.remember(
        "The user prefers concise Chinese status updates",
        tags=("preference", "language"),
        source="test",
    )
    run_entry = memory.remember(
        "The report data was loaded from local.csv",
        scope="run:test-run",
        kind="progress",
    )

    results = memory.recall("Chinese status", scopes=("global",), limit=4)
    assert [entry.id for entry in results] == [global_entry.id]
    assert results[0].tags == ("preference", "language")

    results = memory.recall("local.csv", scopes=("run:test-run", "global"), limit=4)
    assert [entry.id for entry in results] == [run_entry.id]
    assert memory.list(scope="run:test-run")[0].content.endswith("local.csv")


def test_memory_store_bounds_and_rejects_empty_content(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "state.db")
    memory.initialize()
    try:
        memory.remember("   ")
    except ValueError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("empty memory should be rejected")

    try:
        memory.remember("x" * 20_001)
    except ValueError as exc:
        assert "20 KiB" in str(exc)
    else:
        raise AssertionError("oversized memory should be rejected")
