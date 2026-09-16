"""Execute an admitted multi-file candidate in a private workspace.

The runner is deliberately a narrow process boundary.  It revalidates the immutable admission,
source bundle bytes, and staged input bytes immediately before launch.  It never writes execution
evidence, touches Store/Candidate state, imports candidate code, or invokes an evaluator.
"""
from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ._benchmark_files import BenchmarkFileError, absolute_path
from ._candidate_workspace_io import DirectoryChain, identity
from .candidate_bundle import CandidateBundleError, verify_candidate_source_bundle
from .candidate_execution import (
    CandidateExecutionAdmission,
    CandidateExecutionError,
    admit_candidate_execution,
)
from .candidate_workspace_plan import (
    CandidateWorkspaceError,
    CandidateWorkspacePlan,
    validate_candidate_workspace_plan,
)
from .evolution import CandidateExecution

CANDIDATE_INPUT_ROOT_ENV = "LUNAR_CANDIDATE_INPUT_ROOT"
MAX_COMMAND_ARGS = 32
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_RESULT_OUTPUT_BYTES = 16 * 1024
MIN_PROCESS_TIMEOUT_SECONDS = 0.05
PROCESS_CLEANUP_GRACE_SECONDS = 0.25
PROCESS_READ_CHUNK_BYTES = 64 * 1024


class CandidateExecutionRunnerError(ValueError):
    """Fixed public runner failure codes without paths or OS prose."""

    _CODES = frozenset({
        "invalid", "workspace_unsafe", "input_unsafe", "plan_mismatch", "bundle_changed", "executable_unsafe",
        "bundle_mismatch", "contract_mismatch", "identity_mismatch", "budget_invalid",
        "input_changed", "process_start_failed", "process_timed_out", "output_limit_exceeded",
        "process_failed", "process_cleanup_failed",
    })

    def __init__(self, code: str) -> None:
        suffix = code.removeprefix("candidate_execution_runner_") if isinstance(code, str) else ""
        self.code = "candidate_execution_runner_" + (suffix if suffix in self._CODES else "invalid")
        super().__init__(self.code)


def _kill_group(process: subprocess.Popen[str]) -> bool:
    try:
        os.killpg(process.pid, signal.SIGKILL)
        return True
    except ProcessLookupError:
        return True
    except OSError:
        try:
            process.kill()
            return process.poll() is not None
        except (OSError, ProcessLookupError):
            return process.poll() is not None


def _bounded(value: object, limit: int) -> tuple[str, bool]:
    if isinstance(value, bytes):
        raw = value
    else:
        text = value if isinstance(value, str) else ""
        raw = text.encode("utf-8", errors="replace")
    overflow = len(raw) > limit
    if overflow:
        raw = raw[:limit]
    text = raw.decode("utf-8", errors="replace")
    encoded = text.encode("utf-8")
    if len(encoded) > limit:
        overflow = True
        text = encoded[:limit].decode("utf-8", errors="ignore")
    return text, overflow


def _bounded_process(
    command: list[str], *, cwd: str, environment: dict[str, str], timeout: float, output_limit: int,
) -> tuple[str, str, Literal["succeeded", "failed", "timed_out"], int | None, str | None]:
    """Run a process while keeping each captured stream bounded in memory.

    Pipes are consumed as bytes with a selector rather than through ``communicate``.  This both
    keeps output storage bounded and lets timeout/overflow cleanup stop waiting for a descendant
    that inherited the pipes.  A short post-kill grace period captures ordinary trailing output;
    pipes are then closed even if a detached descendant still holds them open.
    """
    process: subprocess.Popen[bytes] | None = None
    selector: selectors.BaseSelector | None = None
    streams: list[object] = []
    output = {"stdout": bytearray(), "stderr": bytearray()}
    totals = {"stdout": 0, "stderr": 0}
    overflow = False
    reason: Literal["timeout", "overflow"] | None = None
    cleanup_ok = True
    cleanup_deadline: float | None = None
    exit_code: int | None = None
    started = time.monotonic()
    capture_limit = min(output_limit, MAX_RESULT_OUTPUT_BYTES)

    def terminate() -> None:
        nonlocal cleanup_ok, cleanup_deadline
        if cleanup_deadline is not None:
            return
        cleanup_ok = _kill_group(process) if process is not None else False
        cleanup_deadline = time.monotonic() + PROCESS_CLEANUP_GRACE_SECONDS

    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            start_new_session=True,
        )
        assert process.stdout is not None and process.stderr is not None
        streams = [process.stdout, process.stderr]
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        deadline = started + timeout
        while True:
            now = time.monotonic()
            if reason is None:
                if now >= deadline:
                    reason = "timeout"
                    terminate()
                elif process.poll() is not None:
                    exit_code = process.returncode
                    terminate()
            if cleanup_deadline is not None and now >= cleanup_deadline:
                if selector.get_map():
                    cleanup_ok = False
                break
            if not selector.get_map() and process.poll() is not None:
                break
            wait_for = 0.05
            if reason is None:
                wait_for = min(wait_for, max(0.0, deadline - now))
            if cleanup_deadline is not None:
                wait_for = min(wait_for, max(0.0, cleanup_deadline - now))
            for key, _ in selector.select(wait_for):
                stream_name = key.data
                try:
                    chunk = os.read(key.fileobj.fileno(), PROCESS_READ_CHUNK_BYTES)
                except (BlockingIOError, InterruptedError):
                    continue
                if not chunk:
                    try:
                        selector.unregister(key.fileobj)
                    except (KeyError, ValueError):
                        pass
                    continue
                totals[stream_name] += len(chunk)
                if len(output[stream_name]) < capture_limit:
                    remaining = capture_limit - len(output[stream_name])
                    output[stream_name].extend(chunk[:remaining])
                if totals[stream_name] > output_limit and reason is None:
                    overflow = True
                    reason = "overflow"
                    terminate()
    finally:
        if selector is not None:
            selector.close()
        for stream in streams:
            try:
                stream.close()  # type: ignore[union-attr]
            except OSError:
                pass
        if process is not None and process.poll() is None:
            cleanup_ok = _kill_group(process) and cleanup_ok
            try:
                process.wait(timeout=PROCESS_CLEANUP_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except (OSError, ProcessLookupError):
                    pass
                try:
                    process.wait(timeout=PROCESS_CLEANUP_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    cleanup_ok = False

    if process is not None and exit_code is None and reason != "timeout":
        exit_code = process.returncode
    stdout, stdout_overflow = _bounded(bytes(output["stdout"]), output_limit)
    stderr, stderr_overflow = _bounded(bytes(output["stderr"]), output_limit)
    overflow = overflow or stdout_overflow or stderr_overflow
    if reason == "timeout" and cleanup_ok:
        return stdout, stderr, "timed_out", None, "process_timed_out"
    if overflow:
        return stdout, stderr, "failed", exit_code, "output_limit_exceeded"
    if not cleanup_ok:
        return stdout, stderr, "failed", exit_code, "process_cleanup_failed"
    if exit_code == 0:
        return stdout, stderr, "succeeded", exit_code, None
    return stdout, stderr, "failed", exit_code, "process_failed"


@dataclass(frozen=True)
class CandidateExecutionRun:
    """Path-free metadata returned by one admitted process invocation."""

    execution: CandidateExecution
    admission_sha256: str
    workspace_plan_sha256: str
    bundle_sha256: str
    input_count: int
    total_input_bytes: int
    entrypoint: str

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.execution.status,
            "execution": {
                "status": self.execution.status,
                "exit_code": self.execution.exit_code,
                "duration_ms": self.execution.duration_ms,
                "stdout_bytes": self.execution.stdout_bytes,
                "stderr_bytes": self.execution.stderr_bytes,
                "error": self.execution.error,
            },
            "admission_sha256": self.admission_sha256,
            "workspace_plan_sha256": self.workspace_plan_sha256,
            "bundle_sha256": self.bundle_sha256,
            "input_count": self.input_count,
            "total_input_bytes": self.total_input_bytes,
            "entrypoint": self.entrypoint,
        }


class CandidateExecutionRunner:
    """Run a plan's explicit command against a verified workspace and input namespace."""

    def __init__(self, *, max_output_bytes: int | None = None) -> None:
        if max_output_bytes is not None and (
            isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int)
            or not 0 < max_output_bytes <= MAX_OUTPUT_BYTES
        ):
            raise CandidateExecutionRunnerError("invalid")
        self.max_output_bytes = max_output_bytes

    def run(
        self,
        admission: CandidateExecutionAdmission | Mapping[str, object] | str | bytes,
        *,
        plan: CandidateWorkspacePlan | Mapping[str, object],
        workspace_path: str | os.PathLike[str],
        input_path: str | os.PathLike[str],
        expected_admission_sha256: str | None = None,
        expected_plan_sha256: str | None = None,
        expected_bundle_sha256: str | None = None,
        expected_contract_sha256: str | None = None,
    ) -> CandidateExecutionRun:
        try:
            parsed_plan = validate_candidate_workspace_plan(
                plan if isinstance(plan, CandidateWorkspacePlan) else CandidateWorkspacePlan.from_dict(dict(plan))
            )
        except (CandidateWorkspaceError, TypeError, ValueError, KeyError, AttributeError) as exc:
            if isinstance(exc, CandidateWorkspaceError):
                raise CandidateExecutionRunnerError("plan_mismatch") from None
            raise CandidateExecutionRunnerError("invalid") from None
        try:
            verified = admit_candidate_execution(
                admission,
                plan=parsed_plan,
                input_root=None,
                expected_admission_sha256=expected_admission_sha256,
                expected_plan_sha256=expected_plan_sha256,
                expected_bundle_sha256=expected_bundle_sha256,
                expected_contract_sha256=expected_contract_sha256,
            )
        except CandidateExecutionError as exc:
            suffix = exc.code.removeprefix("candidate_execution_")
            raise CandidateExecutionRunnerError("input_changed" if suffix in {"input_missing", "input_changed"} else suffix) from None
        if verified.admission.budget.max_processes != 1:
            raise CandidateExecutionRunnerError("invalid")
        try:
            workspace = absolute_path(workspace_path)
        except BenchmarkFileError:
            raise CandidateExecutionRunnerError("workspace_unsafe") from None
        try:
            inputs = absolute_path(input_path)
        except BenchmarkFileError:
            raise CandidateExecutionRunnerError("input_unsafe") from None
        workspace_chain = input_chain = None
        def close_chains() -> None:
            for chain in (input_chain, workspace_chain):
                if chain is not None:
                    try: chain.close()
                    except OSError: pass
        try:
            workspace_chain = DirectoryChain(workspace, "workspace_unsafe")
            input_chain = DirectoryChain(inputs, "input_unsafe")
            # Shared ordinary ancestors (for example `/` and the user's home directory) are
            # expected.  Reject only when either selected root is itself an ancestor of the
            # other, which would make the source and input namespaces overlap.
            workspace_id = identity(os.fstat(workspace_chain.fd))
            input_id = identity(os.fstat(input_chain.fd))
            workspace_ancestors = {identity(os.fstat(fd)) for fd in workspace_chain.fds}
            input_ancestors = {identity(os.fstat(fd)) for fd in input_chain.fds}
            if workspace_id in input_ancestors or input_id in workspace_ancestors:
                raise CandidateExecutionRunnerError("workspace_unsafe")
            workspace_chain.check(); input_chain.check()
            wr = workspace.absolute()
            ir = inputs.absolute()
        except CandidateExecutionRunnerError:
            close_chains()
            raise
        except CandidateWorkspaceError as exc:
            close_chains()
            code = "input_unsafe" if exc.code.endswith("input_unsafe") else "workspace_unsafe"
            raise CandidateExecutionRunnerError(code) from None
        except OSError:
            close_chains()
            raise CandidateExecutionRunnerError("workspace_unsafe") from None
        try:
            verified = admit_candidate_execution(
                verified.admission,
                plan=parsed_plan,
                input_root=inputs,
                expected_admission_sha256=expected_admission_sha256,
                expected_plan_sha256=expected_plan_sha256,
                expected_bundle_sha256=expected_bundle_sha256,
                expected_contract_sha256=expected_contract_sha256,
            )
        except CandidateExecutionError as exc:
            suffix = exc.code.removeprefix("candidate_execution_")
            close_chains()
            raise CandidateExecutionRunnerError(
                "input_changed" if suffix in {"input_missing", "input_changed"} else suffix,
            ) from None
        try:
            verify_candidate_source_bundle(
                parsed_plan.bundle,
                source_root=wr,
                contract_sha256=parsed_plan.contract_sha256,
                expected_bundle_sha256=verified.admission.bundle_sha256,
            )
        except CandidateBundleError:
            close_chains()
            raise CandidateExecutionRunnerError("bundle_changed") from None
        command = tuple(parsed_plan.command)
        if len(command) >= MAX_COMMAND_ARGS:
            for chain in (input_chain, workspace_chain):
                if chain is not None: chain.close()
            raise CandidateExecutionRunnerError("invalid")
        executable = Path(command[0])
        try:
            if executable.is_symlink() or not executable.is_file() or not os.access(executable, os.X_OK):
                close_chains()
                raise CandidateExecutionRunnerError("executable_unsafe")
        except OSError:
            close_chains()
            raise CandidateExecutionRunnerError("executable_unsafe") from None
        environment = {key: value for key, value in parsed_plan.environment}
        if CANDIDATE_INPUT_ROOT_ENV in environment:
            close_chains()
            raise CandidateExecutionRunnerError("invalid")
        environment[CANDIDATE_INPUT_ROOT_ENV] = str(ir)
        timeout = max(parsed_plan.timeout_seconds, MIN_PROCESS_TIMEOUT_SECONDS)
        output_limit = parsed_plan.max_output_bytes if self.max_output_bytes is None else self.max_output_bytes
        if output_limit > verified.admission.budget.max_output_bytes:
            close_chains()
            raise CandidateExecutionRunnerError("invalid")
        started = time.monotonic()
        try:
            workspace_chain.check(); input_chain.check()
            stdout, stderr, status, exit_code, error = _bounded_process(
                [*command, parsed_plan.entrypoint], cwd=str(wr), environment=environment,
                timeout=timeout, output_limit=output_limit,
            )
        except OSError:
            stdout = stderr = ""
            status = "failed"
            exit_code = None
            error = "process_start_failed"
        finally:
            close_chains()
        duration_ms = min(86_400_000, max(0, round((time.monotonic() - started) * 1000)))
        execution = CandidateExecution(status, exit_code, duration_ms, stdout, stderr, error)
        return CandidateExecutionRun(
            execution, verified.admission_sha256, parsed_plan.digest(), parsed_plan.bundle_sha256,
            verified.input_count, verified.total_input_bytes, parsed_plan.entrypoint,
        )


def run_candidate_execution(
    admission: CandidateExecutionAdmission | Mapping[str, object] | str | bytes,
    *, plan: CandidateWorkspacePlan | Mapping[str, object], workspace_path: str | os.PathLike[str],
    input_path: str | os.PathLike[str], expected_admission_sha256: str | None = None,
    expected_plan_sha256: str | None = None, expected_bundle_sha256: str | None = None,
    expected_contract_sha256: str | None = None,
) -> CandidateExecutionRun:
    return CandidateExecutionRunner().run(
        admission, plan=plan, workspace_path=workspace_path, input_path=input_path,
        expected_admission_sha256=expected_admission_sha256,
        expected_plan_sha256=expected_plan_sha256, expected_bundle_sha256=expected_bundle_sha256,
        expected_contract_sha256=expected_contract_sha256,
    )


__all__ = [
    "CANDIDATE_INPUT_ROOT_ENV",
    "CandidateExecutionRun",
    "CandidateExecutionRunner",
    "CandidateExecutionRunnerError",
    "run_candidate_execution",
]
