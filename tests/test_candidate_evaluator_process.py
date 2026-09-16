"""Raw evaluator reports retain their full bounded bytes before strict parsing."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from famou import candidate_execution_runner as runner

REPORT_LIMIT = 32 * 1024


def invoke(tmp_path: Path, program: str, *, timeout: float = 2, limit: int = REPORT_LIMIT):
    return runner._bounded_process_bytes(
        [str(Path(sys.executable).resolve()), "-I", "-c", program],
        cwd=str(tmp_path.resolve()), environment={}, timeout=timeout,
        output_limit=limit, capture_limit=limit,
    )


def test_report_larger_than_candidate_telemetry_capture_is_complete(tmp_path):
    stdout, stderr, status, code, error = invoke(
        tmp_path, 'import json; print(json.dumps({"payload": "x" * 20000}))',
    )
    assert len(stdout) > runner.MAX_RESULT_OUTPUT_BYTES
    assert json.loads(stdout) == {"payload": "x" * 20000}
    assert stderr == b""
    assert (status, code, error) == ("succeeded", 0, None)


@pytest.mark.parametrize("descriptor", [1, 2])
@pytest.mark.parametrize("excess", [0, 1])
def test_raw_stream_limit_is_exact_and_capture_stays_bounded(tmp_path, descriptor, excess):
    stdout, stderr, status, _, error = invoke(
        tmp_path, f"import os; os.write({descriptor}, b'x' * {REPORT_LIMIT + excess})",
    )
    streams = {1: stdout, 2: stderr}
    assert streams[descriptor] == b"x" * REPORT_LIMIT
    assert streams[3 - descriptor] == b""
    assert status == ("failed" if excess else "succeeded")
    assert error == ("output_limit_exceeded" if excess else None)


def test_invalid_utf8_is_returned_unchanged_for_strict_report_parser(tmp_path):
    stdout, stderr, status, code, error = invoke(
        tmp_path, "import os; os.write(1, b'\\xff\\xc0'); os.write(2, b'\\xfe')",
    )
    assert stdout == b"\xff\xc0"
    assert stderr == b"\xfe"
    assert (status, code, error) == ("succeeded", 0, None)
    with pytest.raises(UnicodeDecodeError):
        stdout.decode("utf-8")


def test_capture_limit_can_be_smaller_than_process_output_limit(tmp_path):
    stdout, stderr, status, code, error = runner._bounded_process_bytes(
        [str(Path(sys.executable).resolve()), "-I", "-c", "import os; os.write(1, b'x' * 20000)"],
        cwd=str(tmp_path.resolve()), environment={}, timeout=2,
        output_limit=REPORT_LIMIT, capture_limit=64,
    )
    assert stdout == b"x" * 64
    assert stderr == b""
    assert (status, code, error) == ("succeeded", 0, None)


def test_raw_process_failure_preserves_report_bytes_without_accepting_them(tmp_path):
    stdout, stderr, status, code, error = invoke(
        tmp_path, 'import os; os.write(1, b"{}\\n"); raise SystemExit(7)',
    )
    assert stdout == b"{}\n"
    assert stderr == b""
    assert (status, code, error) == ("failed", 7, "process_failed")


def test_raw_timeout_stops_process_within_cleanup_bound(tmp_path):
    started = time.monotonic()
    stdout, stderr, status, code, error = invoke(
        tmp_path, "import time; time.sleep(10)", timeout=0.02,
    )
    assert time.monotonic() - started < 1.5
    assert stdout == stderr == b""
    assert (status, code, error) == ("timed_out", None, "process_timed_out")


def test_raw_process_cleans_up_descendant_holding_output_pipe(tmp_path):
    started = time.monotonic()
    stdout, stderr, status, code, error = runner._bounded_process_bytes(
        ["/bin/sh", "-c", "sleep 10 & printf done"],
        cwd=str(tmp_path.resolve()), environment={}, timeout=2,
        output_limit=REPORT_LIMIT, capture_limit=REPORT_LIMIT,
    )
    assert time.monotonic() - started < 1.5
    assert stdout == b"done"
    assert stderr == b""
    assert (status, code, error) == ("succeeded", 0, None)


def test_failed_cleanup_cannot_be_reported_as_clean_timeout(tmp_path, monkeypatch):
    kill = runner._kill_group

    def uncertain(process):
        kill(process)
        return False

    monkeypatch.setattr(runner, "_kill_group", uncertain)
    _, _, status, _, error = invoke(tmp_path, "import time; time.sleep(10)", timeout=0.02)
    assert (status, error) == ("failed", "process_cleanup_failed")


def test_candidate_text_wrapper_keeps_telemetry_truncation_and_replacement(tmp_path):
    stdout, stderr, status, code, error = runner._bounded_process(
        [str(Path(sys.executable).resolve()), "-I", "-c", "import os; os.write(1, b'x' * 20000)"],
        cwd=str(tmp_path.resolve()), environment={}, timeout=2, output_limit=REPORT_LIMIT,
    )
    assert stdout == "x" * runner.MAX_RESULT_OUTPUT_BYTES
    assert stderr == ""
    assert (status, code, error) == ("succeeded", 0, None)
    stdout, _, status, code, error = runner._bounded_process(
        [str(Path(sys.executable).resolve()), "-I", "-c", "import os; os.write(1, b'\\xff')"],
        cwd=str(tmp_path.resolve()), environment={}, timeout=2, output_limit=1,
    )
    assert stdout == ""
    assert (status, code, error) == ("failed", 0, "output_limit_exceeded")
