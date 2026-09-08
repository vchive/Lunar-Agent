import importlib.util
import json
import subprocess
import sys
import venv
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from famou import effect_preflight
from famou.cli import main
from famou.effect_preflight import EffectPreflightError, run_effect_preflight

_trial_spec = importlib.util.spec_from_file_location(
    "effect_trial_fixture", Path(__file__).with_name("test_effect_trial.py")
)
assert _trial_spec is not None and _trial_spec.loader is not None
_trial_module = importlib.util.module_from_spec(_trial_spec)
_trial_spec.loader.exec_module(_trial_module)
_fixture = _trial_module._fixture


def test_effect_preflight_validates_without_running_trial_processes(tmp_path: Path) -> None:
    suite, baseline, case_root, subject, harness = _fixture(tmp_path)
    report_path = tmp_path / "preflight.json"
    report = run_effect_preflight(
        suite,
        baseline,
        case_sources={"fixture_case": case_root},
        subject_command=subject,
        harness_command=(*harness, "--python", str(Path(sys.executable).resolve())),
        requested_model="gpt-5.6-sol",
        harness_python=Path(sys.executable).resolve(),
        harness_imports=("json",),
        harness_packages=(),
        output=report_path,
    )

    assert report["status"] == "ready"
    assert report["protocol"] == "famou-bench-effect-preflight-v1"
    assert report["harness"]["imports"] == {"json": True}
    assert report["harness"]["environment_names"] == []
    assert report_path.exists()
    persisted = report_path.read_text(encoding="utf-8")
    assert str(tmp_path) not in persisted
    assert "subject.py" not in persisted
    assert "harness.py" not in persisted


def test_effect_preflight_requires_interpreter_binding(tmp_path: Path) -> None:
    suite, baseline, case_root, subject, harness = _fixture(tmp_path)
    with pytest.raises(EffectPreflightError, match="--python"):
        run_effect_preflight(
            suite,
            baseline,
            case_sources={"fixture_case": case_root},
            subject_command=subject,
            harness_command=harness,
            requested_model="gpt-5.6-sol",
            harness_python=Path(sys.executable).resolve(),
        )


def test_effect_preflight_rejects_missing_dependency(tmp_path: Path) -> None:
    suite, baseline, case_root, subject, harness = _fixture(tmp_path)
    command = (*harness, "--python", str(Path(sys.executable).resolve()))
    with pytest.raises(EffectPreflightError, match="missing declared imports"):
        run_effect_preflight(
            suite,
            baseline,
            case_sources={"fixture_case": case_root},
            subject_command=subject,
            harness_command=command,
            requested_model="gpt-5.6-sol",
            harness_python=Path(sys.executable).resolve(),
            harness_imports=("module_that_does_not_exist_for_preflight",),
            harness_packages=("definitely-not-installed-for-preflight==1",),
        )


def test_effect_preflight_rejects_malformed_dependency_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del tmp_path

    class FakeResult:
        returncode = 0
        stdout = b'{"imports":{"json":"yes"},"packages":{},"version":"3.11.0"}'
        stderr = b""

    monkeypatch.setattr(effect_preflight.subprocess, "run", lambda *args, **kwargs: FakeResult())
    with pytest.raises(EffectPreflightError, match="invalid import observations"):
        effect_preflight._probe_interpreter(Path(sys.executable).resolve(), ("json",), ())


def test_effect_preflight_resolves_dotted_modules_without_executing_packages(tmp_path: Path) -> None:
    environment = tmp_path / "harness-venv"
    venv.EnvBuilder(with_pip=False, symlinks=False).create(environment)
    interpreter = environment / "bin" / "python"
    installed = Path(subprocess.check_output(
        [str(interpreter), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        text=True,
    ).strip())
    marker = tmp_path / "package-executed"
    package = installed / "preflight_side_effect"
    nested = package / "nested"
    nested.mkdir(parents=True)
    side_effect = f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
    (package / "__init__.py").write_text(side_effect, encoding="utf-8")
    (nested / "__init__.py").write_text(side_effect, encoding="utf-8")
    (nested / "leaf.py").write_text(side_effect, encoding="utf-8")
    namespace = installed / "preflight_namespace" / "nested"
    namespace.mkdir(parents=True)
    (namespace / "leaf.py").write_text(side_effect, encoding="utf-8")

    observed = effect_preflight._probe_interpreter(interpreter, (
        "preflight_side_effect.nested.leaf",
        "preflight_side_effect.nested.missing",
        "preflight_namespace.nested.leaf",
        "sys",
    ), ())

    assert observed["imports"] == {
        "preflight_side_effect.nested.leaf": True,
        "preflight_side_effect.nested.missing": False,
        "preflight_namespace.nested.leaf": True,
        "sys": True,
    }
    assert not marker.exists()
    assert not list(installed.rglob("__pycache__"))


@pytest.mark.parametrize("label", ["subject", "harness"])
def test_effect_preflight_rejects_nonexecutable_commands_before_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, label: str
) -> None:
    suite, baseline, case_root, subject, harness = _fixture(tmp_path)
    interpreter = Path(sys.executable).resolve()
    blocked = tmp_path / "not-executable"
    blocked.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    blocked.chmod(0o600)
    if label == "subject":
        subject = (str(blocked),)
    else:
        harness = (str(blocked),)

    def no_probe(*args, **kwargs):
        raise AssertionError("invalid commands must be rejected before the dependency probe")

    monkeypatch.setattr(effect_preflight, "_probe_interpreter", no_probe)
    with pytest.raises(EffectPreflightError, match=f"{label} command.*executable"):
        run_effect_preflight(
            suite,
            baseline,
            case_sources={"fixture_case": case_root},
            subject_command=subject,
            harness_command=(*harness, "--python", str(interpreter)),
            requested_model="gpt-5.6-sol",
            harness_python=interpreter,
        )


@pytest.mark.parametrize("symlink", [False, True])
def test_effect_preflight_atomic_report_never_overwrites_concurrent_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, symlink: bool
) -> None:
    output = tmp_path / "preflight.json"
    existing = tmp_path / "existing.json"
    existing.write_bytes(b"existing report")
    real_link = effect_preflight.os.link

    def racing_link(source, destination, **kwargs):
        if symlink:
            output.symlink_to(existing)
        else:
            output.write_bytes(b"concurrent report")
        return real_link(source, destination, **kwargs)

    monkeypatch.setattr(effect_preflight.os, "link", racing_link)
    with pytest.raises(EffectPreflightError, match="new regular file"):
        effect_preflight._atomic_report(output, {"status": "ready"})

    assert existing.read_bytes() == b"existing report"
    assert output.is_symlink() == symlink
    assert output.read_bytes() == (b"existing report" if symlink else b"concurrent report")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["existing.json", "preflight.json"]


def test_effect_preflight_atomic_report_rejects_symlink_parent(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(private, target_is_directory=True)

    with pytest.raises(EffectPreflightError, match="parent.*symlink"):
        effect_preflight._atomic_report(alias / "report.json", {"status": "ready"})

    assert not list(private.iterdir())


def test_effect_preflight_report_is_json_safe(tmp_path: Path) -> None:
    suite, baseline, case_root, subject, harness = _fixture(tmp_path)
    report = run_effect_preflight(
        suite,
        baseline,
        case_sources={"fixture_case": case_root},
        subject_command=subject,
        harness_command=(*harness, "--python", str(Path(sys.executable).resolve())),
        requested_model="gpt-5.6-sol",
        harness_python=Path(sys.executable).resolve(),
    )
    assert json.loads(json.dumps(report)) == report


def test_effect_preflight_cli_emits_credential_safe_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    suite, baseline, case_root, subject, harness = _fixture(tmp_path)
    interpreter = Path(sys.executable).resolve()
    monkeypatch.setenv("PREFLIGHT_SECRET", "do-not-persist")
    output = tmp_path / "cli-preflight.json"
    code = main(
        [
            "effect-preflight",
            str(suite),
            str(baseline),
            "--case-source",
            f"fixture_case={case_root}",
            "--subject-command",
            " ".join(subject),
            "--harness-command",
            " ".join((*harness, "--python", str(interpreter))),
            "--requested-model",
            "gpt-5.6-sol",
            "--harness-python",
            str(interpreter),
            "--harness-import",
            "json",
            "--subject-env",
            "PREFLIGHT_SECRET",
            "--output",
            str(output),
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ready"
    persisted = output.read_text(encoding="utf-8")
    assert "do-not-persist" not in persisted
    assert str(tmp_path) not in persisted


def test_effect_preflight_cli_rejects_missing_explicit_environment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    suite, baseline, case_root, subject, harness = _fixture(tmp_path)
    interpreter = Path(sys.executable).resolve()
    code = main(
        [
            "effect-preflight",
            str(suite),
            str(baseline),
            "--case-source",
            f"fixture_case={case_root}",
            "--subject-command",
            " ".join(subject),
            "--harness-command",
            " ".join((*harness, "--python", str(interpreter))),
            "--requested-model",
            "gpt-5.6-sol",
            "--harness-python",
            str(interpreter),
            "--subject-env",
            "MISSING_EFFECT_PREFLIGHT_ENV",
            "--json",
        ]
    )

    assert code == 2
    error = json.loads(capsys.readouterr().err)["error"]
    assert "not set" in error


def test_effect_preflight_rejects_changed_model_profile_digest(tmp_path: Path) -> None:
    suite, baseline, case_root, subject, harness = _fixture(tmp_path)
    interpreter = Path(sys.executable).resolve()
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"name": "fixture", "model": "gpt-5.6-sol"}), encoding="utf-8")
    with pytest.raises(EffectPreflightError, match="model profile digest"):
        run_effect_preflight(
            suite,
            baseline,
            case_sources={"fixture_case": case_root},
            subject_command=subject,
            harness_command=(*harness, "--python", str(interpreter)),
            requested_model="gpt-5.6-sol",
            harness_python=interpreter,
            model_profile_sha256="0" * 64,
            subject_model_profile_path=profile,
        )


def test_effect_preflight_rejects_symlinked_model_profile(tmp_path: Path) -> None:
    suite, baseline, case_root, subject, harness = _fixture(tmp_path)
    interpreter = Path(sys.executable).resolve()
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "model": "gpt-5.6-sol",
                "endpoint": "https://example.invalid/v1",
                "api_key_env": "FAMOU_API_KEY",
                "max_turns": 1,
                "max_tokens": 1,
                "timeout_seconds": 1,
                "max_cost_micros": 1,
            }
        ),
        encoding="utf-8",
    )
    alias = tmp_path / "profile-alias.json"
    alias.symlink_to(profile)
    with pytest.raises(EffectPreflightError, match="model profile"):
        run_effect_preflight(
            suite,
            baseline,
            case_sources={"fixture_case": case_root},
            subject_command=subject,
            harness_command=(*harness, "--python", str(interpreter)),
            requested_model="gpt-5.6-sol",
            harness_python=interpreter,
            subject_model_profile_path=alias,
        )
