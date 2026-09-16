"""Independent filesystem, interruption, and replay boundaries for recorded candidate execution."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time

import pytest
from test_candidate_execution_evidence import fixture, inspect

from famou import CandidateExecutionEvidenceError, run_candidate_execution_recorded
from famou import candidate_execution_evidence as evidence

FILES = ("launch-intent.json", "result.json", "completed.json")
PREFIX = "candidate_execution_evidence_"


def _snapshot(directory):
    return {p.name: (p.lstat().st_ino, p.read_bytes()) for p in directory.iterdir() if p.is_file()}


def _inode(path):
    info = path.stat()
    return info.st_dev, info.st_ino


def _assert_fixed(error, secret=None):
    assert type(error.value) is CandidateExecutionEvidenceError
    assert str(error.value) == error.value.code
    assert error.value.code.startswith(PREFIX)
    if secret is not None:
        assert secret not in str(error.value)


@pytest.mark.parametrize("kind", ["directory", "file", "symlink", "fifo"])
def test_existing_attempt_node_never_runs_or_changes_existing_bytes(tmp_path, monkeypatch, kind):
    admission, request = fixture(tmp_path)
    path = request["attempt_path"]
    outside = tmp_path / "retained"
    outside.write_bytes(b"retained")
    if kind == "directory":
        path.mkdir()
        (path / "retained").write_bytes(b"retained")
    elif kind == "file":
        path.write_bytes(b"retained")
    elif kind == "symlink":
        path.symlink_to(outside)
    else:
        os.mkfifo(path)
    before = path.lstat()
    monkeypatch.setattr(evidence, "run_candidate_execution", lambda *a, **k: pytest.fail("runner called"))

    with pytest.raises(CandidateExecutionEvidenceError) as error:
        run_candidate_execution_recorded(admission, **request)

    assert error.value.code == PREFIX + "attempt_exists"
    _assert_fixed(error, str(tmp_path))
    assert (path.lstat().st_dev, path.lstat().st_ino, path.lstat().st_mode) == (
        before.st_dev, before.st_ino, before.st_mode,
    )
    assert outside.read_bytes() == b"retained"
    assert not (request["workspace_path"] / "count").exists()


@pytest.mark.parametrize("root", ["workspace_path", "input_path", "attempt_parent"])
@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_unsafe_roots_fail_before_attempt_or_runner(tmp_path, monkeypatch, root, kind):
    admission, request = fixture(tmp_path)
    alias = tmp_path / ("unsafe-" + root)
    target = tmp_path if root == "attempt_parent" else request[root]
    if kind == "symlink":
        alias.symlink_to(target, target_is_directory=True)
    else:
        os.mkfifo(alias)
    if root == "attempt_parent":
        request["attempt_path"] = alias / "attempt"
    else:
        request[root] = alias
    monkeypatch.setattr(evidence, "run_candidate_execution", lambda *a, **k: pytest.fail("runner called"))

    with pytest.raises(CandidateExecutionEvidenceError) as error:
        run_candidate_execution_recorded(admission, **request)

    assert error.value.code == PREFIX + "root_unsafe"
    _assert_fixed(error, str(tmp_path))
    assert not (tmp_path / "attempt").exists()


@pytest.mark.parametrize("root", ["workspace_path", "input_path"])
def test_attempt_inside_source_or_input_is_rejected_before_creation(tmp_path, root):
    admission, request = fixture(tmp_path)
    request["attempt_path"] = request[root] / "attempt"
    with pytest.raises(CandidateExecutionEvidenceError, match=PREFIX + "root_unsafe"):
        run_candidate_execution_recorded(admission, **request)
    assert not request["attempt_path"].exists()


@pytest.mark.parametrize("name", FILES)
@pytest.mark.parametrize("kind", ["symlink", "fifo", "directory", "hardlink"])
def test_retained_record_nodes_must_be_independent_regular_files(tmp_path, name, kind):
    admission, request = fixture(tmp_path)
    run_candidate_execution_recorded(admission, **request)
    path = request["attempt_path"] / name
    saved = tmp_path / ("saved-" + name)
    path.rename(saved)
    if kind == "symlink":
        path.symlink_to(saved)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    else:
        os.link(saved, path)
    before = path.lstat()
    saved_bytes = saved.read_bytes()

    with pytest.raises(CandidateExecutionEvidenceError) as error:
        inspect(admission, request)

    _assert_fixed(error, str(tmp_path))
    assert path.lstat().st_ino == before.st_ino
    assert saved.read_bytes() == saved_bytes
    assert (request["workspace_path"] / "count").read_text() == "x"


@pytest.mark.parametrize("name", ["launch-intent.json", "result.json"])
def test_same_bytes_replaced_with_new_inode_do_not_satisfy_completion(tmp_path, name):
    admission, request = fixture(tmp_path)
    run_candidate_execution_recorded(admission, **request)
    path = request["attempt_path"] / name
    original_inode = _inode(path)
    replacement = tmp_path / "replacement"
    replacement.write_bytes(path.read_bytes())
    replacement.replace(path)
    assert _inode(path) != original_inode

    with pytest.raises(CandidateExecutionEvidenceError, match=PREFIX + "identity_mismatch"):
        inspect(admission, request)


def test_copied_attempt_directory_cannot_rebind_the_original_record(tmp_path):
    admission, request = fixture(tmp_path)
    run_candidate_execution_recorded(admission, **request)
    original = request["attempt_path"]
    retained = tmp_path / "retained-attempt"
    original.rename(retained)
    original.mkdir()
    for path in retained.iterdir():
        (original / path.name).write_bytes(path.read_bytes())
    before = _snapshot(original)

    with pytest.raises(CandidateExecutionEvidenceError, match=PREFIX + "identity_mismatch"):
        inspect(admission, request)

    assert _snapshot(original) == before
    assert (retained / "completed.json").is_file()


@pytest.mark.parametrize("mutation", ["replace-file", "modify-file", "replace-attempt"])
def test_inode_and_directory_replacements_during_read_fail_closed(tmp_path, monkeypatch, mutation):
    admission, request = fixture(tmp_path)
    run_candidate_execution_recorded(admission, **request)
    attempt = request["attempt_path"]
    target = attempt / "result.json"
    wanted = _inode(target)
    original_read = os.read
    changed = False

    def mutate(descriptor, count):
        nonlocal changed
        content = original_read(descriptor, count)
        info = os.fstat(descriptor)
        if content and not changed and (info.st_dev, info.st_ino) == wanted:
            changed = True
            if mutation == "replace-file":
                replacement = tmp_path / "replacement"
                replacement.write_bytes(target.read_bytes())
                replacement.replace(target)
            elif mutation == "modify-file":
                data = target.read_bytes()
                target.write_bytes(data.replace(b'"succeeded"', b'"successxx"'))
            else:
                attempt.rename(tmp_path / "held-attempt")
                attempt.mkdir()
                (attempt / "foreign").write_bytes(b"do not remove")
        return content

    monkeypatch.setattr(os, "read", mutate)
    with pytest.raises(CandidateExecutionEvidenceError) as error:
        inspect(admission, request)
    assert changed
    _assert_fixed(error, str(tmp_path))
    if mutation == "replace-attempt":
        assert (attempt / "foreign").read_bytes() == b"do not remove"


@pytest.mark.parametrize("name", FILES)
@pytest.mark.parametrize("operation", ["write", "fsync"])
@pytest.mark.parametrize("interruption", ["oserror", "interrupt"])
def test_partial_record_write_or_sync_retains_uncertain_attempt(
    tmp_path, monkeypatch, name, operation, interruption,
):
    admission, request = fixture(tmp_path)
    temporary = request["attempt_path"] / ("." + name + ".tmp")
    original = getattr(os, operation)
    interrupted = False

    def inject(descriptor, *args):
        nonlocal interrupted
        info = os.fstat(descriptor)
        try:
            matches = stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == _inode(temporary)
        except FileNotFoundError:
            matches = False
        if matches and not interrupted:
            interrupted = True
            if operation == "write":
                content = args[0]
                original(descriptor, content[:max(1, len(content) // 2)])
            if interruption == "interrupt":
                raise KeyboardInterrupt
            raise OSError("private-write-path=/DO-NOT-LEAK")
        return original(descriptor, *args)

    expected = KeyboardInterrupt if interruption == "interrupt" else CandidateExecutionEvidenceError
    with monkeypatch.context() as patch:
        patch.setattr(os, operation, inject)
        with pytest.raises(expected) as error:
            run_candidate_execution_recorded(admission, **request)
    assert interrupted and temporary.is_file()
    if interruption == "oserror":
        _assert_fixed(error, "/DO-NOT-LEAK")
    before = _snapshot(request["attempt_path"])
    assert inspect(admission, request).status == "uncertain"
    assert _snapshot(request["attempt_path"]) == before
    with pytest.raises(CandidateExecutionEvidenceError, match=PREFIX + "attempt_exists"):
        run_candidate_execution_recorded(admission, **request)
    marker = request["workspace_path"] / "count"
    assert (marker.read_text() if marker.exists() else "") == ("" if name == "launch-intent.json" else "x")


@pytest.mark.parametrize("name", FILES)
def test_interruption_after_link_retains_temp_and_is_uncertain(tmp_path, monkeypatch, name):
    admission, request = fixture(tmp_path)
    original = os.unlink
    temporary = "." + name + ".tmp"

    def interrupted(path, *args, **kwargs):
        if path == temporary and "dir_fd" in kwargs:
            raise KeyboardInterrupt
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "unlink", interrupted)
        with pytest.raises(KeyboardInterrupt):
            run_candidate_execution_recorded(admission, **request)
    attempt = request["attempt_path"]
    assert (attempt / temporary).is_file()
    assert (attempt / name).is_file()
    before = _snapshot(attempt)
    assert inspect(admission, request).status == "uncertain"
    assert _snapshot(attempt) == before
    with pytest.raises(CandidateExecutionEvidenceError, match=PREFIX + "attempt_exists"):
        run_candidate_execution_recorded(admission, **request)


@pytest.mark.parametrize("name", FILES)
@pytest.mark.parametrize("mutation", ["newline", "duplicate-key", "oversized", "nonfinite", "extra-secret-field"])
def test_invalid_record_encoding_uses_fixed_path_free_errors(tmp_path, name, mutation):
    admission, request = fixture(tmp_path)
    run_candidate_execution_recorded(admission, **request)
    target = request["attempt_path"] / name
    content = target.read_bytes()
    if mutation == "newline":
        content += b"\n"
    elif mutation == "duplicate-key":
        content = b'{"schema_version":"1",' + content[1:]
    elif mutation == "oversized":
        content = b" " * (evidence.MAX_EXECUTION_RECORD_BYTES + 1)
    elif mutation == "nonfinite":
        content = b'{"secret":NaN}'
    else:
        decoded = json.loads(content)
        decoded["PRIVATE=/DO-NOT-LEAK"] = "api_key=do-not-leak-this"
        content = evidence._encode(decoded)
    target.write_bytes(content)
    before = _snapshot(request["attempt_path"])

    with pytest.raises(CandidateExecutionEvidenceError) as error:
        inspect(admission, request)

    _assert_fixed(error, "DO-NOT-LEAK")
    assert "do-not-leak-this" not in str(error.value)
    assert _snapshot(request["attempt_path"]) == before


def test_completion_without_result_is_error_not_uncertain(tmp_path):
    admission, request = fixture(tmp_path)
    run_candidate_execution_recorded(admission, **request)
    (request["attempt_path"] / "result.json").unlink()
    with pytest.raises(CandidateExecutionEvidenceError, match=PREFIX + "record_changed"):
        inspect(admission, request)


@pytest.mark.parametrize("field", [
    "expected_admission_sha256", "expected_plan_sha256", "expected_bundle_sha256",
    "expected_contract_sha256",
])
def test_every_caller_pin_replays_before_inspection_io(tmp_path, monkeypatch, field):
    admission, request = fixture(tmp_path)
    run_candidate_execution_recorded(admission, **request)
    monkeypatch.setattr(evidence, "_open", lambda *a, **k: pytest.fail("pin opened retained root"))
    with pytest.raises(CandidateExecutionEvidenceError) as error:
        inspect(admission, request, **{field: "0" * 64})
    _assert_fixed(error)


@pytest.mark.parametrize("field", [
    "workspace_plan_sha256", "admission_sha256", "bundle_sha256", "contract_sha256",
    "source_file_table_sha256", "input_file_table_sha256",
])
def test_each_retained_declaration_binding_is_checked(tmp_path, field):
    admission, request = fixture(tmp_path)
    run_candidate_execution_recorded(admission, **request)
    target = request["attempt_path"] / "launch-intent.json"
    value = json.loads(target.read_bytes())
    value["binding"][field] = "0" * 64
    target.write_bytes(evidence._encode(value))
    with pytest.raises(CandidateExecutionEvidenceError, match=PREFIX + "identity_mismatch"):
        inspect(admission, request)


@pytest.mark.parametrize("error_class", [RuntimeError, ValueError])
def test_unexpected_runner_exception_is_redacted_and_preserves_intent(tmp_path, monkeypatch, error_class):
    admission, request = fixture(tmp_path)

    def failed(*args, **kwargs):
        raise error_class("/PRIVATE/DO-NOT-LEAK api_key=super-secret")

    monkeypatch.setattr(evidence, "run_candidate_execution", failed)
    with pytest.raises(CandidateExecutionEvidenceError) as error:
        run_candidate_execution_recorded(admission, **request)
    _assert_fixed(error, "DO-NOT-LEAK")
    assert "super-secret" not in str(error.value)
    assert inspect(admission, request).status == "uncertain"


@pytest.mark.parametrize("inserted", [".result.json.tmp", "foreign"])
def test_new_directory_entry_during_inspection_cannot_be_missed(tmp_path, monkeypatch, inserted):
    admission, request = fixture(tmp_path)
    run_candidate_execution_recorded(admission, **request)
    original_read = evidence._read
    changed = False

    def read_and_insert(chain, name, **kwargs):
        nonlocal changed
        result = original_read(chain, name, **kwargs)
        if name == "completed.json" and not changed:
            changed = True
            (request["attempt_path"] / inserted).write_bytes(b"retained interruption")
        return result

    monkeypatch.setattr(evidence, "_read", read_and_insert)
    with pytest.raises(CandidateExecutionEvidenceError, match=PREFIX + "record_changed"):
        inspect(admission, request)
    assert changed
    assert (request["attempt_path"] / inserted).read_bytes() == b"retained interruption"


def test_failed_initial_directory_sync_keeps_empty_attempt_reserved(tmp_path, monkeypatch):
    admission, request = fixture(tmp_path)
    original = os.fsync
    wanted = _inode(tmp_path)

    def fail_parent_sync(descriptor):
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) == wanted:
            raise OSError("private parent sync /DO-NOT-LEAK")
        return original(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fail_parent_sync)
        with pytest.raises(CandidateExecutionEvidenceError) as error:
            run_candidate_execution_recorded(admission, **request)
    _assert_fixed(error, "DO-NOT-LEAK")
    assert request["attempt_path"].is_dir()
    assert list(request["attempt_path"].iterdir()) == []
    assert inspect(admission, request).status == "uncertain"
    with pytest.raises(CandidateExecutionEvidenceError, match=PREFIX + "attempt_exists"):
        run_candidate_execution_recorded(admission, **request)
    assert not (request["workspace_path"] / "count").exists()


def test_attempt_replacement_during_intent_write_never_launches_or_deletes_foreign_tree(tmp_path, monkeypatch):
    admission, request = fixture(tmp_path)
    attempt = request["attempt_path"]
    retained = tmp_path / "retained-attempt"
    original = os.write
    changed = False

    def write_and_replace(descriptor, content):
        nonlocal changed
        result = original(descriptor, content)
        if not changed:
            changed = True
            attempt.rename(retained)
            attempt.mkdir()
            (attempt / "foreign").write_bytes(b"do not delete")
        return result

    monkeypatch.setattr(os, "write", write_and_replace)
    monkeypatch.setattr(evidence, "run_candidate_execution", lambda *a, **k: pytest.fail("runner called"))
    with pytest.raises(CandidateExecutionEvidenceError) as error:
        run_candidate_execution_recorded(admission, **request)
    _assert_fixed(error)
    assert changed
    assert (attempt / "foreign").read_bytes() == b"do not delete"
    assert (retained / ".launch-intent.json.tmp").is_file()
    assert not (request["workspace_path"] / "count").exists()


_CRASH_WORKER = r"""
import json, os, sys
from famou import run_candidate_execution_recorded
from famou import candidate_execution_evidence as evidence
payload = json.loads(sys.argv[1])
boundary = payload["boundary"]
real_runner = evidence.run_candidate_execution
real_write = evidence._write
real_unlink = os.unlink
def runner(*args, **kwargs):
    if boundary == "before_runner":
        os._exit(91)
    result = real_runner(*args, **kwargs)
    if boundary == "after_runner":
        os._exit(91)
    return result
def write(chain, name, value):
    result = real_write(chain, name, value)
    if (boundary == "after_result" and name == "result.json") or (
        boundary == "after_completion" and name == "completed.json"
    ):
        os._exit(91)
    return result
def unlink(path, *args, **kwargs):
    if boundary == "completion_link" and path == ".completed.json.tmp":
        os._exit(91)
    return real_unlink(path, *args, **kwargs)
evidence.run_candidate_execution = runner
evidence._write = write
os.unlink = unlink
run_candidate_execution_recorded(payload["admission"], **payload["request"])
"""


@pytest.mark.parametrize("boundary", [
    "before_runner", "after_runner", "after_result", "completion_link", "after_completion",
])
def test_process_crash_retains_exact_record_and_never_grants_replay(tmp_path, boundary):
    admission, request = fixture(tmp_path)
    payload = {
        "boundary": boundary, "admission": admission.to_dict(),
        "request": {key: (value.to_dict() if key == "plan" else str(value)) for key, value in request.items()},
    }
    crashed = subprocess.run(
        [sys.executable, "-c", _CRASH_WORKER, json.dumps(payload)],
        capture_output=True, text=True, timeout=5, check=False,
    )
    assert crashed.returncode == 91, crashed.stderr
    before = _snapshot(request["attempt_path"])
    result = inspect(admission, request)
    assert result.status == ("recorded" if boundary == "after_completion" else "uncertain")
    assert _snapshot(request["attempt_path"]) == before
    with pytest.raises(CandidateExecutionEvidenceError, match=PREFIX + "attempt_exists"):
        run_candidate_execution_recorded(admission, **request)
    marker = request["workspace_path"] / "count"
    assert (marker.read_text() if marker.exists() else "") == ("" if boundary == "before_runner" else "x")


_WORKER = r"""
import json, os, sys, time
from pathlib import Path
from famou import run_candidate_execution_recorded, CandidateExecutionEvidenceError
from famou import candidate_execution_evidence as evidence
payload = json.loads(sys.argv[1])
request = payload["request"]
Path(payload["ready"]).write_text("ready")
deadline = time.monotonic() + 5
while not Path(payload["gate"]).exists():
    if time.monotonic() > deadline:
        raise RuntimeError("gate timeout")
    time.sleep(0.01)
real = evidence.run_candidate_execution
def slowed(*args, **kwargs):
    time.sleep(0.15)
    return real(*args, **kwargs)
evidence.run_candidate_execution = slowed
try:
    result = run_candidate_execution_recorded(payload["admission"], **request)
    print(json.dumps({"status": result.status}))
except CandidateExecutionEvidenceError as error:
    print(json.dumps({"status": error.code}))
"""


def test_concurrent_real_processes_authorize_only_one_attempt(tmp_path):
    admission, request = fixture(tmp_path)
    serialized = {key: (value.to_dict() if key == "plan" else str(value)) for key, value in request.items()}
    gate = tmp_path / "gate"
    children = []
    try:
        for number in range(2):
            payload = {
                "request": serialized, "admission": admission.to_dict(),
                "ready": str(tmp_path / ("ready-" + str(number))), "gate": str(gate),
            }
            children.append(subprocess.Popen(
                [sys.executable, "-c", _WORKER, json.dumps(payload)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            ))
        deadline = time.monotonic() + 5
        while not all((tmp_path / ("ready-" + str(number))).exists() for number in range(2)):
            assert time.monotonic() < deadline
            time.sleep(0.01)
        gate.write_text("go")
        outcomes = []
        for child in children:
            stdout, stderr = child.communicate(timeout=5)
            assert child.returncode == 0, stderr
            outcomes.append(json.loads(stdout)["status"])
        assert sorted(outcomes) == sorted(["recorded", PREFIX + "attempt_exists"])
        assert (request["workspace_path"] / "count").read_text() == "x"
        before = _snapshot(request["attempt_path"])
        assert inspect(admission, request).status == "recorded"
        assert _snapshot(request["attempt_path"]) == before
        with pytest.raises(CandidateExecutionEvidenceError, match=PREFIX + "attempt_exists"):
            run_candidate_execution_recorded(admission, **request)
        assert (request["workspace_path"] / "count").read_text() == "x"
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)


@pytest.mark.parametrize("interface", ["api", "cli"])
def test_close_oserror_is_fixed_and_preserves_record(tmp_path, monkeypatch, capsys, interface):
    from famou import cli

    admission, request = fixture(tmp_path)
    record = run_candidate_execution_recorded(admission, **request)
    before = _snapshot(request["attempt_path"])
    admission_path, plan_path = tmp_path / "admission.json", tmp_path / "plan.json"
    admission_path.write_text(json.dumps(admission.to_dict()))
    plan_path.write_text(json.dumps(request["plan"].to_dict()))
    original_close = evidence.DirectoryChain.close
    closed = []

    def close_then_fail(chain):
        closed.extend(chain.fds)
        original_close(chain)
        raise OSError("/PRIVATE/DO-NOT-LEAK close failure")

    with monkeypatch.context() as patch:
        patch.setattr(evidence.DirectoryChain, "close", close_then_fail)
        if interface == "api":
            with pytest.raises(CandidateExecutionEvidenceError) as error:
                inspect(admission, request)
            _assert_fixed(error, "DO-NOT-LEAK")
            assert error.value.code == PREFIX + "record_changed"
        else:
            patch.setattr(cli, "_config", lambda *_: pytest.fail("Store/home initialized"))
            assert cli.main([
                "candidate-bundle", "inspect-execution", str(admission_path), "--plan", str(plan_path),
                "--attempt", str(request["attempt_path"]), "--home", str(tmp_path / "no-home"), "--json",
            ]) == 2
            output = capsys.readouterr()
            assert output.out == ""
            assert json.loads(output.err) == {"error": PREFIX + "record_changed"}
            assert not (tmp_path / "no-home").exists()
    assert closed
    for descriptor in closed:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    assert _snapshot(request["attempt_path"]) == before
    assert inspect(admission, request) == record
    assert (request["workspace_path"] / "count").read_text() == "x"


def _fail_first_outer_close(monkeypatch, request):
    original_open = evidence._open
    handles, closed = [], []

    def tracked_open(value):
        path, chain = original_open(value)
        handles.append(chain)
        original_close = chain.close

        def close():
            original_close()
            closed.append(chain)
            if path == request["attempt_path"]:
                raise OSError("/PRIVATE/DO-NOT-LEAK close failure")

        monkeypatch.setattr(chain, "close", close)
        return path, chain

    monkeypatch.setattr(evidence, "_open", tracked_open)
    return handles, closed


def test_writer_closes_other_chains_after_first_close_failure(tmp_path, monkeypatch):
    admission, request = fixture(tmp_path)
    with monkeypatch.context() as patch:
        handles, closed = _fail_first_outer_close(patch, request)
        with pytest.raises(CandidateExecutionEvidenceError) as error:
            run_candidate_execution_recorded(admission, **request)
        _assert_fixed(error, "DO-NOT-LEAK")
        assert error.value.code == PREFIX + "record_changed"
    assert len(handles) == 4
    assert closed == list(reversed(handles))
    assert all(chain.fds == [] for chain in handles)
    assert inspect(admission, request).status == "recorded"
    with pytest.raises(CandidateExecutionEvidenceError, match=PREFIX + "attempt_exists"):
        run_candidate_execution_recorded(admission, **request)
    assert (request["workspace_path"] / "count").read_text() == "x"


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("stop"), SystemExit(23)])
def test_original_runner_interruption_survives_close_failure(tmp_path, monkeypatch, interruption):
    admission, request = fixture(tmp_path)

    def interrupted(*_args, **_kwargs):
        raise interruption

    with monkeypatch.context() as patch:
        handles, closed = _fail_first_outer_close(patch, request)
        patch.setattr(evidence, "run_candidate_execution", interrupted)
        with pytest.raises(type(interruption)) as error:
            run_candidate_execution_recorded(admission, **request)
        assert error.value is interruption
    assert len(handles) == 4
    assert closed == list(reversed(handles))
    assert all(chain.fds == [] for chain in handles)
    assert inspect(admission, request).status == "uncertain"
    assert not (request["workspace_path"] / "count").exists()
    with pytest.raises(CandidateExecutionEvidenceError, match=PREFIX + "attempt_exists"):
        run_candidate_execution_recorded(admission, **request)


def test_directory_chain_closes_remaining_descriptors_after_close_error(tmp_path, monkeypatch):
    chain = evidence.DirectoryChain(tmp_path, "record_changed")
    wanted = list(reversed(chain.fds))
    closed = []
    original_close = os.close

    def close_then_fail(descriptor):
        original_close(descriptor)
        closed.append(descriptor)
        if descriptor == wanted[0]:
            raise OSError("private close failure")

    with monkeypatch.context() as patch:
        patch.setattr(os, "close", close_then_fail)
        with pytest.raises(OSError, match="private close failure"):
            chain.close()
    assert closed == wanted
    assert chain.fds == []
    for descriptor in wanted:
        with pytest.raises(OSError):
            os.fstat(descriptor)


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("write stopped"), SystemExit(27)])
def test_record_write_interruption_survives_file_close_failure(tmp_path, monkeypatch, interruption):
    admission, request = fixture(tmp_path)
    interrupted_fd = None
    original_close = os.close

    def interrupted_write(descriptor, _content):
        nonlocal interrupted_fd
        interrupted_fd = descriptor
        raise interruption

    def close_then_fail(descriptor):
        original_close(descriptor)
        if descriptor == interrupted_fd:
            raise OSError("private close failure")

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", interrupted_write)
        patch.setattr(os, "close", close_then_fail)
        patch.setattr(evidence, "run_candidate_execution", lambda *_a, **_k: pytest.fail("runner called"))
        with pytest.raises(type(interruption)) as error:
            run_candidate_execution_recorded(admission, **request)
        assert error.value is interruption
    assert interrupted_fd is not None
    assert inspect(admission, request).status == "uncertain"
    assert (request["attempt_path"] / ".launch-intent.json.tmp").is_file()
    assert not (request["workspace_path"] / "count").exists()
