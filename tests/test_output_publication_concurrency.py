"""Real-process contention must serialize one parent publication and its exact replay."""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from famou.store import Store

_PUBLISHER = r'''
import fcntl
import json
import sys
import time
from pathlib import Path

import famou.output_publication as publication
from famou.algorithm import OutputSpec
from famou.store import Store

database, parent_id, child_id, owner, barrier_directory, mode = sys.argv[1:]
barriers = Path(barrier_directory)
store = Store(database)
parent = store.get_run(parent_id)
assert parent is not None
prepared = [
    (OutputSpec("output/first.txt", "text"), b"first verified output\n"),
    (OutputSpec("output/nested/second.txt", "text"), b"second verified output\n"),
]
if mode == "first":
    original_write = publication._write_new

    def pause_after_staging(path, content):
        original_write(path, content)
        if path.name == "00.blob":
            (barriers / "first-staged").write_text("holding parent lock", encoding="utf-8")
            deadline = time.monotonic() + 15
            while not (barriers / "release-first").exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("first publisher release barrier was not reached")
                time.sleep(0.01)

    publication._write_new = pause_after_staging
else:
    original_flock = fcntl.flock

    def observe_contended_lock(descriptor, operation):
        if operation != fcntl.LOCK_EX:
            return original_flock(descriptor, operation)
        # The nonblocking probe proves the first process actually holds this same lock.
        try:
            original_flock(descriptor, operation | fcntl.LOCK_NB)
        except BlockingIOError:
            (barriers / "second-contended").write_text("waiting for parent lock", encoding="utf-8")
        else:
            raise AssertionError("second publisher entered while the first was staging")
        original_flock(descriptor, operation)
        (barriers / "second-acquired").write_text("parent lock acquired", encoding="utf-8")

    fcntl.flock = observe_contended_lock

outputs = publication.publish_outputs(store, parent, child_id, owner, prepared, 1000000)
print(json.dumps(outputs, sort_keys=True), flush=True)
'''


def _wait_for_barrier(path: Path, processes: list[subprocess.Popen[str]]) -> None:
    deadline = time.monotonic() + 15
    while not path.exists():
        for process in processes:
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=1)
                raise AssertionError(
                    f"publisher exited before {path.name}: {process.returncode}\n"
                    f"{stdout}\n{stderr}"
                )
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out waiting for {path.name}")
        time.sleep(0.01)


def test_parent_lock_serializes_two_real_publishers_at_staging(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    parent = store.create_run("publish concurrent verified outputs", tmp_path / "parent")
    child = store.create_run("evolve one selected candidate", tmp_path / "child")
    owner = store.list_tasks(parent.id)[0].id
    Path(parent.workspace).mkdir(parents=True)
    barriers = tmp_path / "barriers"
    barriers.mkdir()
    command = [
        sys.executable, "-c", _PUBLISHER,
        str(store.database), parent.id, child.id, owner, str(barriers),
    ]
    processes: list[subprocess.Popen[str]] = []
    try:
        first = subprocess.Popen(
            [*command, "first"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        processes.append(first)
        _wait_for_barrier(barriers / "first-staged", processes)

        second = subprocess.Popen(
            [*command, "second"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        processes.append(second)
        _wait_for_barrier(barriers / "second-contended", processes)

        # Neither publisher has passed the staged, uncommitted first process yet.
        assert not (barriers / "second-acquired").exists()
        assert not (Path(parent.workspace) / "output").exists()
        assert store.list_artifacts(parent.id) == []
        (barriers / "release-first").write_text("continue publication", encoding="utf-8")

        first_stdout, first_stderr = first.communicate(timeout=15)
        second_stdout, second_stderr = second.communicate(timeout=15)
        assert first.returncode == 0, first_stderr
        assert second.returncode == 0, second_stderr
        assert (barriers / "second-acquired").is_file()
        first_outputs = json.loads(first_stdout)
        second_outputs = json.loads(second_stdout)
        assert first_outputs == second_outputs
    finally:
        # Bound cleanup even if a barrier assertion or a child process fails.
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=2)

    expected = {
        "output/first.txt": b"first verified output\n",
        "output/nested/second.txt": b"second verified output\n",
    }
    assert [output["path"] for output in first_outputs] == list(expected)
    rows = store.list_artifacts(parent.id)
    assert len(rows) == 2
    assert {row["id"] for row in rows} == {output["artifact_id"] for output in first_outputs}
    for row in rows:
        content = expected[row["path"]]
        assert row["kind"] == "output"
        assert row["task_id"] == owner
        assert row["size"] == len(content)
        assert row["sha256"] == hashlib.sha256(content).hexdigest()
        assert (Path(parent.workspace) / row["path"]).read_bytes() == content
    events = store.list_events(parent.id)
    assert len([event for event in events if event["type"] == "artifact_recorded"]) == 2
    promotions = [event for event in events if event["type"] == "evolved_outputs_promoted"]
    commits = [event for event in events if event["type"] == "output_publication_committed"]
    assert len(promotions) == len(commits) == 1
    assert promotions[0]["payload"] == {
        "evolution_run_id": child.id,
        "outputs": first_outputs,
    }
    assert commits[0]["payload"]["evolution_run_id"] == child.id
