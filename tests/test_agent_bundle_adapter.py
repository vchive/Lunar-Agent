"""Command Agent transport must preserve complete bundle responses for validation."""

import json
import sys
from pathlib import Path

import pytest

from famou.agents import AgentRequest, CommandAgentAdapter


def _invoke(tmp_path, response):
    response_path = tmp_path / "response.json"
    response_path.write_text(response)
    adapter = CommandAgentAdapter((
        str(Path(sys.executable).resolve()), "-c",
        "import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text())",
        str(response_path),
    ))
    return adapter.run(AgentRequest("bundle-run", "generation", "solver", "generate", workspace=tmp_path))


def test_direct_command_agent_response_preserves_all_files_and_experiment(tmp_path):
    payload = {
        "entrypoint": "solve/main.py",
        "files": {"solve/main.py": "from helper import choose\n", "solve/helper.py": "def choose(): return 7\n"},
        "metadata": {"family": "fixture"},
        "experiment": {"schema_version": "1", "hypothesis": "Change the helper only."},
    }
    raw = json.dumps(payload, indent=2)
    result = _invoke(tmp_path, raw)
    assert result.status == "succeeded"
    assert result.text == raw
    assert json.loads(result.text) == payload


@pytest.mark.parametrize("raw", [
    '{"entrypoint":"main.py","files":{"main.py":"pass","helper.py":"first","helper.py":"second"}}',
    '{"entrypoint":"main.py","files":{"main.py":"first"},"files":{"main.py":"second"}}',
    '{"source":"pass","filename":"main.py","entrypoint":"main.py","files":{"main.py":"pass","helper.py":"secret = 1"}}',
])
def test_command_normalization_does_not_erase_ambiguous_bundle_fields(tmp_path, raw):
    # The bundle parser must see the ambiguity, rather than a normalized last-wins object or
    # a single-file projection which silently discards the helper.
    assert _invoke(tmp_path, raw).text == raw
