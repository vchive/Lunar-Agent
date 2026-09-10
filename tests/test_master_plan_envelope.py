"""Grammar-only tests for bounded, unambiguous Master handoff envelopes."""
import json

import pytest

from famou import staged_workflow
from famou.workflow_checkpoint import WorkflowCheckpointError

PLAN = {"plan": ["Save a complete candidate"], "expected_paths": ["solution.json", "_agent_summary.md"]}
BODY = json.dumps(PLAN)
LIMIT = 128 * 1024


def parse(text):
    return staged_workflow._parse_master_response(text)


@pytest.mark.parametrize("text", [
    BODY,
    " \t\r\n" + BODY + "\n\t ",
    "```json\n" + BODY + "\n```",
    "I inspected the public inputs.\n```json\n" + BODY + "\n```\nBuild can follow this plan.",
    "Explanation with `inline code`.\n\t ```json \t\n" + BODY + "\n \t```\t \nDone.",
    "An inline ```example``` is plain prose.\n```json\n" + BODY + "\n```",
    "\r\n解释文本\r\n\t```json\t\r\n" + json.dumps(PLAN, indent=2).replace("\n", "\r\n") + "\r\n```\r\n完成。\r\n",
    "```json\n\n" + json.dumps(PLAN, indent=2) + "\n\n```\n",
])
def test_accepts_only_the_declared_unambiguous_envelopes(text):
    assert parse(text) == PLAN


@pytest.mark.parametrize("body", [
    "{}", '{"plan":[],"expected_paths":[]}',
    '{"unknown":{"value":[null,true,false,1,1.25,1e-5]}}',
    '{"literal":"```json and ~~~ are data; {braces} and [brackets] stay inside"}',
])
@pytest.mark.parametrize("fenced", [False, True])
def test_leaves_semantic_validation_to_the_existing_plan_boundary(body, fenced):
    text = "```json\n" + body + "\n```" if fenced else body
    assert parse(text) == json.loads(body)


@pytest.mark.parametrize("text", [
    "", "Plain explanation only", "[]", "null", "true", "123", '"a string"',
    BODY + "\n{}", BODY + "\nExplanation after a raw object.",
    "Prefix without a fence " + BODY,
    "```json\n" + BODY,
    "```json\n" + BODY + "\n``` trailing text",
    "```json trailing text\n" + BODY + "\n```",
    "```\n" + BODY + "\n```",
    "```JSON\n" + BODY + "\n```",
    "```json5\n" + BODY + "\n```",
    "```yaml\n" + BODY + "\n```",
    "~~~json\n" + BODY + "\n~~~",
    "````json\n" + BODY + "\n````",
    "```json\n" + BODY + "\n````",
    "```json\n" + BODY + "\n~~~",
    "\u00a0```json\n" + BODY + "\n```",
    "```json\u00a0\n" + BODY + "\n```",
    "```json\n" + BODY + "\n```\u00a0",
    "\v```json\n" + BODY + "\n```",
    "\f```json\n" + BODY + "\n```",
    "\u00a0" + BODY,
    "Inline ```json " + BODY + " ```",
    "```json\r" + BODY + "\r```",
    "```json\n" + BODY + "\n```\n```",
    "~~~an extra fence\n```json\n" + BODY + "\n```",
    "```json\n" + BODY + "\n```\n```python\npass\n```",
    "```json\n" + BODY + "\n```\n```json\n" + BODY + "\n```",
    "```json\n" + BODY + "\n{}\n```",
    "```json\n[]\n```", "```json\nnull\n```", "```json\n\n```",
    "```json\n" + BODY + "\nExplanation is not JSON.\n```",
    "```json\n{'plan': []}\n```",
    "```json\n{\"plan\": [],}\n```",
])
def test_rejects_malformed_or_competing_envelopes(text):
    with pytest.raises(WorkflowCheckpointError):
        parse(text)


@pytest.mark.parametrize("character", "{}[]")
@pytest.mark.parametrize("before", [False, True])
def test_rejects_braces_and_brackets_in_discarded_prose(character, before):
    envelope = "```json\n" + BODY + "\n```"
    explanation = "An outside " + character + " marker."
    with pytest.raises(WorkflowCheckpointError):
        parse(explanation + "\n" + envelope if before else envelope + "\n" + explanation)


@pytest.mark.parametrize("body", [
    '{"plan":[],"plan":["replacement"]}',
    '{"nested":{"duplicate":1,"duplicate":2}}',
    '{"nested":[{"duplicate":1,"duplicate":2}]}',
    '{"duplicate":1,"\\u0064uplicate":2}',
    '{"value":NaN}', '{"value":Infinity}', '{"value":-Infinity}',
    '{"value":1e9999}', '{"value":-1e9999}',
    '{"value":[{"nested":NaN}]}',
])
@pytest.mark.parametrize("fenced", [False, True])
def test_rejects_duplicate_keys_and_nonfinite_numbers_at_any_depth(body, fenced):
    with pytest.raises(WorkflowCheckpointError):
        parse("```json\n" + body + "\n```" if fenced else body)


@pytest.mark.parametrize("fenced", [False, True])
def test_complete_original_response_is_bounded_in_utf8_bytes(fenced):
    base = "```json\n" + BODY + "\n```" if fenced else BODY
    # Multibyte explanation is discarded only after the full original byte-size check.
    if fenced:
        prefix_size = LIMIT - len(base.encode()) - 1
        prefix = "说" * (prefix_size // 3) + " " * (prefix_size % 3) + "\n"
    else:
        prefix = " " * (LIMIT - len(base.encode()))
    exact = prefix + base
    assert len(exact.encode()) == LIMIT
    assert parse(exact) == PLAN
    with pytest.raises(WorkflowCheckpointError, match="bounded size"):
        parse(" " + exact)


@pytest.mark.parametrize("text", [
    '{"PRIVATE_DUPLICATE_KEY":1,"PRIVATE_DUPLICATE_KEY":2}',
    '{"PRIVATE_RESPONSE":"unterminated}',
    "PRIVATE_RESPONSE\n```json\n{}\n```\n```",
    "\ud800PRIVATE_RESPONSE",
    '{"value":' + "9" * 5000 + "}",
], ids=["duplicate-key", "malformed", "competing-fence", "surrogate", "oversized-integer"])
def test_rejection_messages_are_bounded_and_do_not_echo_content(text):
    with pytest.raises(WorkflowCheckpointError) as caught:
        parse(text)
    message = str(caught.value)
    assert len(message.encode()) < 128
    assert "PRIVATE" not in message and "duplicate_key" not in message.lower()


def test_decoder_recursion_failure_uses_a_bounded_error(monkeypatch):
    def too_deep(*args, **kwargs):
        raise RecursionError("PRIVATE_RESPONSE")

    monkeypatch.setattr(staged_workflow.json, "loads", too_deep)
    with pytest.raises(WorkflowCheckpointError, match="invalid JSON") as caught:
        parse(BODY)
    assert "PRIVATE_RESPONSE" not in str(caught.value)


def test_size_check_precedes_extraction_and_json_decoder(monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("JSON must not be parsed before the full-response bound")

    monkeypatch.setattr(staged_workflow.json, "loads", forbidden)
    with pytest.raises(WorkflowCheckpointError, match="bounded size"):
        parse("解释" * LIMIT + "\n```json\n{}\n```")
    assert calls == []
