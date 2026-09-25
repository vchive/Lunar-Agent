from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lunar_evolution.linux_executable_binding import (
    LinuxExecutableBindingError,
    sealed_linux_executable,
)


def _identity(path: Path) -> dict[str, int | str]:
    info = path.stat()
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": info.st_size,
        "device": info.st_dev,
        "inode": info.st_ino,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }


def _script(path: Path, value: str) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        f"Path('result').write_text({value!r})\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def test_unsupported_platform_rejects_before_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from lunar_evolution import linux_executable_binding as binding_module

    monkeypatch.setattr(binding_module.sys, "platform", "unsupported")
    with (
        pytest.raises(LinuxExecutableBindingError, match="^linux_execution_binding_unsupported$"),
        sealed_linux_executable(tmp_path / "missing", {}, deadline=float("inf")),
    ):
        pytest.fail("unsupported platform must reject before yielding")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="requires Linux memfd seals")
def test_sealed_shebang_executes_attested_bytes_after_source_replacement(tmp_path: Path):
    source = tmp_path / "producer.py"
    replacement = tmp_path / "replacement.py"
    _script(source, "attested")
    _script(replacement, "replaced")
    expected = _identity(source)

    with sealed_linux_executable(source, expected, deadline=float("inf")) as binding:
        assert binding.binding == "linux-sealed-memfd"
        assert binding.sha256 == expected["sha256"]
        assert binding.size == expected["size"]
        os.replace(replacement, source)
        with pytest.raises(OSError):
            os.write(binding.fd, b"changed")
        result = subprocess.run(
            [source.name], executable=binding.executable, pass_fds=(binding.pass_fd,),
            cwd=tmp_path, env={"PATH": os.defpath, "LANG": "C"}, capture_output=True,
            timeout=3, check=False,
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert (tmp_path / "result").read_text(encoding="utf-8") == "attested"
    with pytest.raises(OSError):
        os.fstat(binding.fd)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="requires Linux memfd seals")
def test_source_identity_drift_rejects_before_binding(tmp_path: Path):
    source = tmp_path / "producer.py"
    _script(source, "attested")
    expected = _identity(source)
    _script(source, "changed")
    with (
        pytest.raises(LinuxExecutableBindingError, match="^linux_execution_source_changed$"),
        sealed_linux_executable(source, expected, deadline=float("inf")),
    ):
        pytest.fail("changed source must reject before yielding")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="requires Linux memfd seals")
def test_sealing_failure_rejects_before_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from lunar_evolution import linux_executable_binding as binding_module

    source = tmp_path / "producer.py"
    _script(source, "attested")
    real_fcntl = binding_module.fcntl.fcntl

    def fail_seal(fd: int, command: int, argument: int = 0) -> int:
        if command == binding_module.fcntl.F_ADD_SEALS:
            raise OSError("sealing denied")
        return real_fcntl(fd, command, argument)

    monkeypatch.setattr(binding_module.fcntl, "fcntl", fail_seal)
    with (
        pytest.raises(LinuxExecutableBindingError, match="^linux_execution_binding_unknown$"),
        sealed_linux_executable(source, _identity(source), deadline=float("inf")),
    ):
        pytest.fail("unsealed bytes must never be handed to Popen")
