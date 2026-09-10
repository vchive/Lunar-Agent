"""The staged CLI is opt-in and loads a frozen per-attempt configuration."""
import json

from test_staged_effect_adapter import StagedSubject, _config, _profile, _request

from famou.cli import main


def test_effect_subject_cli_round_trips_frozen_staged_config(tmp_path, monkeypatch, capsys):
    profile = _profile()
    request = _request(tmp_path / "subject", profile)
    model = StagedSubject()
    monkeypatch.setattr("famou.effect_adapters.OpenAICompatibleRuntime", lambda **kwargs: model)
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict()))
    config = _config(request, profile)
    config_path = tmp_path / "workflow.json"
    config_path.write_text(json.dumps(config.to_dict()))
    status = main([
        "effect-subject", str(request), "--model-profile", str(profile_path),
        "--workflow-config", str(config_path), "--no-exec", "--json",
    ])
    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["usage"]["total_tokens"] == 9
    assert payload["interaction_turns"] == 3
    assert model.turn == 3
    assert json.loads((request.parent / "workflow/config.json").read_text()) == config.to_dict()
