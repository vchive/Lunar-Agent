from pathlib import Path

from famou.cli import main


def test_cli_run_and_status_use_repository_runtime(tmp_path: Path, capsys) -> None:
    assert main(["run", "cli goal", "--runtime", "mock", "--home", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    run_id = next(line.split(": ", 1)[1] for line in output.splitlines() if line.startswith("run_id:"))

    assert main(["status", run_id, "--home", str(tmp_path)]) == 0
    status_output = capsys.readouterr().out
    assert "status: succeeded" in status_output
