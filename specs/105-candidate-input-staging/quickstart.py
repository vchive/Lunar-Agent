"""Run an offline installed-CLI staging example and remove the temporary fixture afterward."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from famou import (
    CandidateEvaluatorPin,
    CandidateExecutionBudget,
    CandidateExecutionInput,
    CandidateSourceBundle,
    build_candidate_execution_admission,
    build_candidate_workspace_plan,
)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="lunar-input-staging-") as temporary:
        root = Path(temporary).resolve()
        source = root / "inputs"
        source.mkdir()
        staging = root / "staging"
        staging.mkdir()
        body = b"sample input\x00\xff"
        (source / "sample.bin").write_bytes(body)
        marker = root / "runner-started"
        plan = build_candidate_workspace_plan(
            CandidateSourceBundle.from_dict({
                "schema_version": "1", "protocol": "lunar-candidate-source-bundle-v1",
                "contract_sha256": "a" * 64, "entrypoint": "main.py",
                "files": [{"path": "main.py", "size": 0, "sha256": hashlib.sha256(b"").hexdigest()}],
            }),
            contract_sha256="a" * 64,
            command=[sys.executable, "-c", f"open({str(marker)!r}, 'w').write('executed')"],
            timeout_seconds=5, max_output_bytes=1024,
        )
        admission = build_candidate_execution_admission(
            plan, inputs=[CandidateExecutionInput(
                "sample.bin", "example", len(body), hashlib.sha256(body).hexdigest(),
            )],
            dependency_sha256="b" * 64, environment_sha256="c" * 64,
            evaluator=CandidateEvaluatorPin("exact-harness", "d" * 64),
            output_contract_sha256="e" * 64, budget=CandidateExecutionBudget(5, 1024, 1024, 1),
        )
        (root / "plan.json").write_text(json.dumps(plan.to_dict()), encoding="utf-8")
        (root / "admission.json").write_text(json.dumps(admission.to_dict()), encoding="utf-8")
        completed = subprocess.run([
            str(Path(sys.executable).parent / "lunar-agent"), "candidate-bundle", "stage-inputs",
            str(root / "admission.json"), "--plan", str(root / "plan.json"),
            "--input-root", str(source), "--staging-root", str(staging),
            "--admission-sha256", admission.digest(), "--home", str(root / "unused-home"), "--json",
        ], capture_output=True, text=True, timeout=15, check=True)
        result = json.loads(completed.stdout)
        input_path = Path(result.pop("input_path"))
        assert input_path.parent == staging
        assert (input_path / "sample.bin").read_bytes() == body
        assert result["admission_sha256"] == admission.digest()
        assert not marker.exists() and not (root / "unused-home").exists()
        assert not completed.stderr
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
