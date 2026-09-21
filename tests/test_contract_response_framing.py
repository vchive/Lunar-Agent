"""Synthetic contract framing cases; no recorded model responses or provider calls."""

import json
from pathlib import Path

import pytest

from lunar_evolution.agent_loop import AgentLoopRuntime
from lunar_evolution.conversational import (
    MAX_RESPONSE_BYTES,
    ContractCompilationError,
    RuntimeContractCompiler,
    _parse_response,
)
from lunar_evolution.runtime import ModelTurn


def _contract() -> dict[str, object]:
    return {
        "schema_version": "1",
        "problem_id": "framing-routing",
        "problem_type": "routing",
        "statement": "Route all orders.",
        "inputs": [{"path": "orders.csv", "format": "csv", "fields": {"id": "order id"}}],
        "decision_variables": ["route order"],
        "objective": {"name": "distance", "direction": "minimize"},
        "hard_constraints": [],
        "soft_constraints": [],
        "success_criteria": ["Every order is served."],
        "deliverables": ["Route table."],
    }


def _compiled() -> str:
    return json.dumps({"status": "compiled", "contract": _contract()})


def _fence(body: str) -> str:
    return "```json\n" + body + "\n```"


NEEDS_INPUT = json.dumps({
    "status": "needs_input",
    "questions": [{"question": "What are the input fields?", "options": ["id", "id, amount"]}],
    "evidence": ["The input schema is unspecified."],
})


@pytest.mark.parametrize("body", [_compiled(), NEEDS_INPUT])
@pytest.mark.parametrize("surrounding", ["", " \t\r\n"])
def test_one_complete_json_fence_preserves_contract_or_questions(body, surrounding):
    assert _parse_response(surrounding + _fence(body) + surrounding) == _parse_response(body)


@pytest.mark.parametrize("response", [
    "Here is the contract:\n" + _fence(_compiled()),
    _fence(_compiled()) + "\nDone.",
    "Here is the contract:\n" + _compiled(),
    _compiled() + "\nDone.",
    "```\n" + _compiled() + "\n```",
    "```JSON\n" + _compiled() + "\n```",
    "``` json\n" + _compiled() + "\n```",
    "```json extra\n" + _compiled() + "\n```",
    "````json\n" + _compiled() + "\n````",
    "~~~json\n" + _compiled() + "\n~~~",
    "```json" + _compiled() + "\n```",
    "```json\n" + _compiled() + "```",
    "```json\r\n" + _compiled() + "\r\n```",
    "```json\r" + _compiled() + "\r```",
    "```json\n" + _compiled() + "\n```extra",
    "\ufeff" + _fence(_compiled()),
    "\u00a0" + _fence(_compiled()),
    _fence(_fence(_compiled())),
    _fence(_compiled()) + "\n" + _fence(_compiled()),
    _fence(_compiled() + "\n" + _compiled()),
    _fence(_compiled() + " // explanatory comment"),
    _fence(_compiled()[:-1] + ",}"),
    _fence('{"status": "compiled", "contract":'),
])
def test_ambiguous_or_invalid_framing_is_not_extracted_or_repaired(response):
    with pytest.raises(ContractCompilationError, match="one strict JSON object"):
        _parse_response(response)


@pytest.mark.parametrize("fenced", [False, True])
@pytest.mark.parametrize("body", [
    '{"status":"needs_input","status":"needs_input","questions":["Schema?"]}',
    '{"status":"needs_input","questions":[{"question":"Schema?","question":"Goal?"}]}',
    '{"status":"needs_input","questions":["Schema?"],"evidence":[NaN]}',
    '{"status":"needs_input","questions":["Schema?"],"evidence":[Infinity]}',
    '{"status":"needs_input","questions":["Schema?"],"evidence":[-Infinity]}',
    '{"status":"needs_input","questions":["Schema?"],"evidence":[1e999]}',
    '{"status":"needs_input","questions":["Schema?"],"evidence":[-1e999]}',
])
def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(body, fenced):
    with pytest.raises(ContractCompilationError, match="one strict JSON object"):
        _parse_response(_fence(body) if fenced else body)


@pytest.mark.parametrize("payload, message", [
    ({"status": "needs_input", "questions": ["Schema?"], "extra": True}, "unknown fields"),
    ({"status": "compiled", "contract": {**_contract(), "extra": True}}, "unknown fields"),
    ({"status": "compiled", "contract": {**_contract(), "evolution": {"max_rounds": True}}}, "invalid"),
    ({"status": "compiled", "contract": {**_contract(), "problem_id": "../escape"}}, "invalid"),
    ({"status": "compiled", "contract": {**_contract(), "evolution": {"strategy": "loop"}}}, "retired"),
    ({"status": "needs_input", "questions": []}, "one to four"),
    ({"status": "needs_input", "questions": ["Schema?"], "contract": _contract()}, "must not include"),
    ([{"status": "needs_input", "questions": ["Schema?"]}], "unknown fields"),
])
def test_framed_payload_obeys_all_existing_schema_rules(payload, message):
    with pytest.raises(ContractCompilationError, match=message):
        _parse_response(_fence(json.dumps(payload)))


def test_fence_bound_includes_envelope_and_outer_whitespace():
    body = _compiled()
    envelope = _fence(body)
    remaining = MAX_RESPONSE_BYTES - len(envelope.encode("utf-8"))
    assert _parse_response(" " * remaining + envelope).status == "compiled"
    with pytest.raises(ContractCompilationError, match="exceeds the bounded limit"):
        _parse_response(" " * (remaining + 1) + envelope)
    body_at_limit = " " * (MAX_RESPONSE_BYTES - len(body.encode("utf-8"))) + body
    assert _parse_response(body_at_limit).status == "compiled"
    with pytest.raises(ContractCompilationError, match="exceeds the bounded limit"):
        _parse_response(_fence(body_at_limit))


def test_bound_counts_utf8_bytes_before_fence_normalization():
    payload = {"status": "compiled", "contract": {**_contract(), "statement": "路线" * 12_000}}
    response = _fence(json.dumps(payload, ensure_ascii=False))
    assert len(response) < MAX_RESPONSE_BYTES < len(response.encode("utf-8"))
    with pytest.raises(ContractCompilationError, match="exceeds the bounded limit"):
        _parse_response(response)


@pytest.mark.parametrize("response", [
    _fence('{"status":"needs_input","questions":["api_key=synthetic-secret-value"]}'),
    "api_key=synthetic-secret-value\n" + _fence(_compiled()),
])
def test_credential_scan_covers_entire_raw_response(response):
    with pytest.raises(ContractCompilationError, match="credential-like content"):
        _parse_response(response)


def test_invalid_unicode_is_normalized_to_compilation_error():
    with pytest.raises(ContractCompilationError, match="valid UTF-8"):
        _parse_response(_fence('\ud800'))


def test_backticks_inside_json_string_are_data_not_a_second_envelope():
    payload = {"status": "needs_input", "questions": ["Does the literal ```json belong in the output?"]}
    body = json.dumps(payload)
    assert _parse_response(_fence(body)) == _parse_response(body)


class RecordingModel:
    name = "synthetic-framing-model"

    def __init__(self, response):
        self.response = response
        self.requests = []

    def complete(self, messages, tools=(), timeout=None):
        self.requests.append((messages, tools, timeout))
        assert len(self.requests) == 1, "contract framing must not issue another model request"
        return ModelTurn(self.response)

    def cancel(self):
        pass

    def process_info(self):
        return None, None

    def set_process_observer(self, observer):
        pass


@pytest.mark.parametrize("valid", [True, False])
def test_isolated_runtime_uses_one_request_without_tools_or_workspace_writes(tmp_path: Path, valid):
    body = _compiled() if valid else _compiled() + "\nExplanation"
    model = RecordingModel(_fence(body))
    compiler = RuntimeContractCompiler(AgentLoopRuntime(model))
    if valid:
        assert compiler.compile("Route all orders", tmp_path, timeout=5).status == "compiled"
    else:
        with pytest.raises(ContractCompilationError, match="one strict JSON object"):
            compiler.compile("Route all orders", tmp_path, timeout=5)
    assert len(model.requests) == 1
    messages, tools, timeout = model.requests[0]
    assert tools == ()
    assert [message["role"] for message in messages] == ["system", "user"]
    assert "no markdown, code fences, surrounding prose, or tool calls" in messages[1]["content"]
    assert 0 < timeout <= 5
    assert list(tmp_path.iterdir()) == []
