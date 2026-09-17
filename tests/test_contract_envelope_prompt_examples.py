"""Offline checks for the complete contract compiler envelope examples."""

import json

import pytest

from famou.conversational import (
    _COMPILED_ENVELOPE_EXAMPLE,
    _NEEDS_INPUT_ENVELOPE_EXAMPLE,
    ContractCompilationError,
    RuntimeContractCompiler,
    _parse_response,
)


def _example_from_prompt(prompt: str, label: str) -> str:
    start = prompt.index(label) + len(label)
    payload, length = json.JSONDecoder().raw_decode(prompt[start:])
    encoded = json.dumps(payload, indent=2)
    assert prompt[start:start + length] == encoded
    return encoded


@pytest.mark.parametrize(
    ("label", "example", "status", "keys"),
    [
        (
            "needs_input example:\n",
            _NEEDS_INPUT_ENVELOPE_EXAMPLE,
            "needs_input",
            {"status", "questions", "evidence"},
        ),
        (
            "compiled example:\n",
            _COMPILED_ENVELOPE_EXAMPLE,
            "compiled",
            {"status", "contract", "evidence"},
        ),
    ],
)
def test_complete_envelope_examples_are_strict_json_accepted_by_native_parser(
    label: str,
    example: str,
    status: str,
    keys: set[str],
) -> None:
    prompt = RuntimeContractCompiler._prompt("Assign current items", None)
    prompt_example = _example_from_prompt(prompt, label)
    payload = json.loads(prompt_example)

    assert prompt_example == example
    assert set(payload) == keys
    assert payload["status"] == status
    assert _parse_response(prompt_example).status == status


def test_compiled_example_is_complete_and_demonstrates_distinct_field_shapes() -> None:
    payload = json.loads(_COMPILED_ENVELOPE_EXAMPLE)
    contract = payload["contract"]
    required_contract_fields = {
        "schema_version",
        "problem_id",
        "problem_type",
        "statement",
        "inputs",
        "decision_variables",
        "objective",
        "hard_constraints",
        "soft_constraints",
        "success_criteria",
        "deliverables",
    }

    assert required_contract_fields <= set(contract)
    assert isinstance(contract["inputs"][0]["fields"], dict)
    assert isinstance(contract["outputs"][0]["fields"], list)
    assert "..." not in _COMPILED_ENVELOPE_EXAMPLE
    result = _parse_response(_COMPILED_ENVELOPE_EXAMPLE)
    assert result.contract is not None
    assert result.contract.problem_id == "example-assignment"


def test_needs_input_example_contains_questions_and_no_contract() -> None:
    payload = json.loads(_NEEDS_INPUT_ENVELOPE_EXAMPLE)
    result = _parse_response(_NEEDS_INPUT_ENVELOPE_EXAMPLE)

    assert "contract" not in payload
    assert result.contract is None
    assert result.questions[0].question == "Which objective should be optimized?"


def test_prompt_contains_each_example_once_before_task_specific_goal() -> None:
    prompt = RuntimeContractCompiler._prompt("TASK_SPECIFIC_GOAL", None)

    assert prompt.count(_NEEDS_INPUT_ENVELOPE_EXAMPLE) == 1
    assert prompt.count(_COMPILED_ENVELOPE_EXAMPLE) == 1
    assert prompt.index(_NEEDS_INPUT_ENVELOPE_EXAMPLE) < prompt.index("Contract schema")
    assert prompt.index(_COMPILED_ENVELOPE_EXAMPLE) < prompt.index("Contract schema")
    assert prompt.index("Contract schema") < prompt.index("TASK_SPECIFIC_GOAL")
    assert "Every response must include the top-level status field" in prompt
    assert "They demonstrate JSON shape only" in prompt
    assert "never copy the example task content" in prompt
    for existing_requirement in (
        "verification_scope",
        'source_check with exactly {"kind":"python_file_count","minimum":2}',
        'never emit the retired "loop"',
    ):
        assert existing_requirement in prompt


def test_examples_do_not_normalize_a_contract_only_response() -> None:
    payload = json.loads(_COMPILED_ENVELOPE_EXAMPLE)
    payload.pop("status")

    with pytest.raises(
        ContractCompilationError,
        match="compiler response must be status=compiled with contract",
    ):
        _parse_response(json.dumps(payload))
