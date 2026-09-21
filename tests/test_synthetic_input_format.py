"""Synthetic evaluator inputs share real-input format admission before execution."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest

from lunar_evolution import data_profile
from lunar_evolution import evaluator_bundle as bundle
from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.evolution import CandidateInputArtifact
from lunar_evolution.runtime import RuntimeResult

ACCEPTED = [
    ("json", b'{"limit":3}'),
    (" JSON ", b'{"unrelated":null}'),
    ("json", b'[{"limit":1},{"limit":null},{"limit":"different"},{}]'),
    ("json", b'[]'),
    ("json", b'{}'),
    ("json", b'{"nested":{"items":[1,null,true,"text"]}}'),
    ("jsonl", b'\n  \n{"limit":1}\n{"other":null}\n\t\n'),
    ("jsonl", b' \n\t\r\n'),
    ("csv", b'limit,other\n1,\n,string\n'),
    ("csv", b'limit\n'),
    ("csv", b'limit,other\n"1,2","two\nlines"\n'),
    ("text", "任意文本\nnot JSON or CSV\x00".encode()),
    ("text", b''),
]
REJECTED = [
    ("json", b'3'),
    ("json", b'null'),
    ("json", b'true'),
    ("json", b'"scalar"'),
    ("json", b'[1,2]'),
    ("json", b'[{"limit":1},3]'),
    ("json", b'{"limit":1,"limit":2}'),
    ("json", b'{"nested":{"limit":1,"limit":2}}'),
    ("json", b'{"limit":NaN}'),
    ("json", b'{"limit":Infinity}'),
    ("json", b'{"limit":1e400}'),
    ("json", b'{broken'),
    ("json", b'{"\\ud800":1}'),
    ("json", b'{"root":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}'),
    ("json", b'{"":1}'),
    ("json", b'{"bad\\u0000field":1}'),
    ("json", b'{"root":' + b'[' * 20 + b'0' + b']' * 20 + b'}'),
    ("jsonl", b'{"limit":1}\n3\n'),
    ("jsonl", b'[]\n'),
    ("jsonl", b'{"limit":1,"limit":2}\n'),
    ("jsonl", b'{"limit":NaN}\n'),
    ("jsonl", b'{broken\n'),
    ("jsonl", b'{"root":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}\n'),
    ("csv", b''),
    ("csv", b',limit\n1,2\n'),
    ("csv", b'limit,limit\n1,2\n'),
    ("csv", b'limit,other\n1\n'),
    ("csv", b'limit\n1,2\n'),
    ("csv", b'limit\n"unclosed\n'),
    ("json", b'\xff'),
    ("jsonl", b'\xff'),
    ("csv", b'\xff'),
    ("text", b'\xff'),
    ("yaml", b'limit: 3'),
]


def _contract(format_name="json", *, second_input=False):
    inputs = [{"path": "limit.json", "format": format_name,
               "fields": {"limit": "A strictly positive integer, as prose only."}}]
    if second_input:
        inputs.append({"path": "nested/other.csv", "format": "csv",
                       "fields": {"id": "ID description, not an enforced schema."}})
    return AlgorithmProblemContract.from_dict({
        "schema_version": "1", "problem_id": "fresh-format-admission-126",
        "problem_type": "continuous", "statement": "Maximize nonnegative result value.",
        "inputs": inputs, "decision_variables": ["value"],
        "objective": {"name": "value", "direction": "maximize"},
        "hard_constraints": [{"id": "nonnegative", "description": "value >= 0",
                              "source": "user_confirmed", "verification": "independent"}],
        "soft_constraints": [], "success_criteria": ["Return a nonnegative value."],
        "deliverables": ["result"],
        "outputs": [{"path": "output/result.json", "format": "json",
                     "fields": ["value"], "required": True}],
    })


def _stage(root, contract, contents):
    descriptors = []
    for spec, content in zip(contract.inputs, contents, strict=True):
        relative = "data/raw/" + spec.path
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        descriptors.append(CandidateInputArtifact(
            relative, len(content), hashlib.sha256(content).hexdigest(),
        ))
    return tuple(descriptors)


@pytest.mark.parametrize("format_name,content", ACCEPTED)
def test_public_input_format_validator_accepts_same_domain_as_real_profile(
    tmp_path, format_name, content,
):
    assert data_profile.validate_input_format(format_name, content) is None
    contract = _contract(format_name)
    descriptors = _stage(tmp_path, contract, [content])
    profile = data_profile.build_private_input_profile(tmp_path, contract, descriptors)
    assert profile["files"][0]["format"] == format_name.strip().lower()


@pytest.mark.parametrize("format_name,content", REJECTED)
def test_public_input_format_validator_rejects_same_domain_as_real_profile(
    tmp_path, format_name, content,
):
    with pytest.raises(data_profile.DataProfileError):
        data_profile.validate_input_format(format_name, content)
    contract = _contract(format_name)
    descriptors = _stage(tmp_path, contract, [content])
    with pytest.raises(data_profile.DataProfileError):
        data_profile.build_private_input_profile(tmp_path, contract, descriptors)


@pytest.mark.parametrize("constant,limit,format_name,content", [
    ("MAX_PROFILE_ROWS", 2, "json", b'[{},{},{}]'),
    ("MAX_PROFILE_ROWS", 2, "jsonl", b'{}\n{}\n{}\n'),
    ("MAX_PROFILE_ROWS", 2, "csv", b'id\na\nb\nc\n'),
    ("MAX_PROFILE_FIELDS", 2, "json", b'{"a":1,"b":2,"c":3}'),
    ("MAX_PROFILE_FIELDS", 2, "jsonl", b'{"a":1}\n{"b":2}\n{"c":3}\n'),
    ("MAX_PROFILE_FIELDS", 2, "csv", b'a,b,c\n'),
    ("MAX_PROFILE_FIELD_BYTES", 3, "json", b'{"long":1}'),
    ("MAX_PROFILE_DEPTH", 2, "json", b'{"outer":{"inner":1}}'),
])
def test_shared_limits_remain_enforced_by_validator_and_profile(
    tmp_path, monkeypatch, constant, limit, format_name, content,
):
    monkeypatch.setattr(data_profile, constant, limit)
    with pytest.raises(data_profile.DataProfileError):
        data_profile.validate_input_format(format_name, content)
    contract = _contract(format_name)
    descriptors = _stage(tmp_path, contract, [content])
    with pytest.raises(data_profile.DataProfileError):
        data_profile.build_private_input_profile(tmp_path, contract, descriptors)


def _source(invocation):
    root = "Path.cwd()" if invocation == "snapshot" else "Path(sys.argv[1]).parent"
    return (
        "import json\nimport sys\nfrom pathlib import Path\n"
        f"root = {root}\n"
        "value = json.loads((root / 'output/result.json').read_text())['value']\n"
        "valid = int(value >= 0)\n"
        "print(json.dumps({'schema_version': '1', 'evaluator_id': 'compiled-bundle',\n"
        " 'validity': valid, 'quality': value if valid else None,\n"
        " 'combined_score': value if valid else 0, 'detailed_scores': {},\n"
        " 'error_info': [] if valid else [{'code': 'nonnegative', 'message': 'negative'}]}))\n"
        "if __name__ == '__main__':\n    pass\n"
    )


def _envelope(invocation, *, second_input=False):
    probes = []
    for name, value in (("small", 1), ("large", 4), ("negative", -1)):
        files = [{"path": "data/raw/limit.json", "content": '{"limit":3}\n'},
                 {"path": "output/result.json", "content": json.dumps({"value": value})}]
        if second_input:
            files.append({"path": "data/raw/nested/other.csv", "content": "id\nfresh\n"})
        probes.append({"name": name, "constraint_id": None if value >= 0 else "nonnegative",
                       "expected_validity": int(value >= 0), "files": files})
    return {"schema_version": "1", "objective": "Maximize valid output value.",
            "evaluator_source": _source(invocation), "constraint_coverage": ["nonnegative"],
            "probes": probes, "score_order": [{"better": "large", "worse": "small"}]}


def _audit(envelope):
    return copy.deepcopy({key: value for key, value in envelope.items()
                          if key not in {"objective", "evaluator_source"}})


class _Runtime:
    name = "synthetic-format-fixture"

    def __init__(self, envelope, audit):
        self.envelope = envelope
        self.audit = audit
        self.calls = []

    def run(self, prompt, workspace, timeout=None):
        if "adversarial evaluator auditor" in prompt:
            self.calls.append("audit")
            return RuntimeResult(json.dumps(self.audit))
        assert "frozen local evaluator bundle" in prompt
        self.calls.append("compiler")
        return RuntimeResult(json.dumps(self.envelope))


def _compile(root, runtime, invocation, *, second_input=False):
    contract = _contract(second_input=second_input)
    contents = [b'{"limit":50}\n']
    if second_input:
        contents.append(b'id\nreal-a\nreal-b\nreal-c\n')
    descriptors = _stage(root, contract, contents)
    return bundle.compile_evaluator_bundle(
        runtime, contract, root, inputs=descriptors, timeout=2, invocation=invocation,
    )


def _track_harness(monkeypatch, invocation):
    calls = []
    name = "_snapshot_probe" if invocation == "snapshot" else "_run_evaluator"
    original = getattr(bundle, name)

    def tracked(*args, **kwargs):
        workspace = args[3] if invocation == "snapshot" else args[1].parent
        calls.append(workspace.parent.name)
        return original(*args, **kwargs)

    monkeypatch.setattr(bundle, name, tracked)
    return calls


@pytest.mark.parametrize("invocation", ["candidate", "snapshot"])
@pytest.mark.parametrize("stage", ["compiler", "audit"])
@pytest.mark.parametrize("input_index,content", [(0, "3\n"), (2, "id,id\nx,y\n")])
def test_late_malformed_declared_input_rejects_whole_suite_before_any_harness(
    tmp_path, monkeypatch, invocation, stage, input_index, content,
):
    envelope = _envelope(invocation, second_input=True)
    audit = _audit(envelope)
    rejected = envelope if stage == "compiler" else audit
    rejected["probes"][-1]["files"][input_index]["content"] = content
    runtime = _Runtime(envelope, audit)
    calls = _track_harness(monkeypatch, invocation)
    with pytest.raises(bundle.EvaluatorBundleError) as error:
        _compile(tmp_path, runtime, invocation, second_input=True)
    assert str(error.value) == f"{stage} probe input violates the declared input format"
    assert error.value.__suppress_context__ is True
    expected_calls = [] if stage == "compiler" else [".compiler-preflight"] * 3
    assert calls == expected_calls
    assert runtime.calls == (["compiler"] if stage == "compiler" else ["compiler", "audit"])
    assert not (tmp_path / "evaluator-bundle").exists()
    assert not list(tmp_path.glob(".evaluator-bundle-*"))


@pytest.mark.parametrize("invocation", ["candidate", "snapshot"])
@pytest.mark.parametrize("content", [
    '{}', '[]', '[{"unrelated":null},{"unrelated":"text"}]',
    '{"limit":null}', '{"limit":"not an integer"}',
])
def test_format_admission_does_not_infer_business_schema_or_profile_statistics(
    tmp_path, invocation, content,
):
    envelope = _envelope(invocation, second_input=True)
    for probe in envelope["probes"]:
        probe["files"][0]["content"] = content
        probe["files"][2]["content"] = "different_header\nsmall\n"
    runtime = _Runtime(envelope, _audit(envelope))
    frozen = _compile(tmp_path, runtime, invocation, second_input=True)
    assert frozen.invocation == invocation
    assert runtime.calls == ["compiler", "audit"]


@pytest.mark.parametrize("invocation", ["candidate", "snapshot"])
def test_preexisting_frozen_fixture_load_does_not_reapply_new_probe_admission(
    tmp_path, monkeypatch, invocation,
):
    envelope = _envelope(invocation)
    for probe in envelope["probes"]:
        probe["files"][0]["content"] = "3\n"
    runtime = _Runtime(envelope, _audit(envelope))
    # Model a pre-126 frozen bundle with fresh synthetic bytes; no historical evidence is used.
    with monkeypatch.context() as prior_admission:
        prior_admission.setattr(bundle, "validate_input_format", lambda *args: None, raising=False)
        frozen = _compile(tmp_path, runtime, invocation)
    before = {path.name: path.read_bytes() for path in frozen.root.iterdir()}
    monkeypatch.setattr(bundle, "_preflight", lambda *a, **k: pytest.fail("recovery reran probes"))
    monkeypatch.setattr(runtime, "run", lambda *a, **k: pytest.fail("recovery called model"))
    resumed = _compile(tmp_path, runtime, invocation)
    loaded = bundle.load_evaluator_bundle(
        frozen.root, _contract(), invocation=invocation, timeout=2,
    )
    assert resumed == loaded == frozen
    assert {path.name: path.read_bytes() for path in frozen.root.iterdir()} == before


@pytest.mark.parametrize("invocation", ["candidate", "snapshot"])
def test_entire_suite_is_admitted_before_any_probe_workspace_is_created(
    tmp_path, monkeypatch, invocation,
):
    envelope = _envelope(invocation)
    envelope["probes"][-1]["files"][0]["content"] = '3'
    suite = bundle._parse_envelope(
        json.dumps(envelope), _contract(), invocation=invocation,
    ).probe_suite()
    evaluator = tmp_path / "evaluator.py"
    evaluator.write_text(_source(invocation))
    monkeypatch.setattr(
        type(tmp_path), "mkdir", lambda *a, **k: pytest.fail("invalid suite created a workspace"),
    )
    with pytest.raises(bundle.EvaluatorBundleError, match="declared input format"):
        bundle._preflight(
            evaluator, suite, _contract(), tmp_path, 2, label="compiler", invocation=invocation,
        )


@pytest.mark.parametrize("invocation", ["candidate", "snapshot"])
@pytest.mark.parametrize("compiler", [True, False])
def test_both_prompts_advertise_input_admission_and_its_semantic_limits(invocation, compiler):
    if compiler:
        prompt = bundle._compiler_prompt(_contract(), {}, invocation=invocation)
    else:
        prompt = bundle._auditor_prompt(
            _contract(), {}, "Maximize nonnegative value.", _source(invocation),
            invocation=invocation,
        )
    for statement in (
        "before any probe in a compiler or auditor suite executes",
        "including expected_validity=0 probes",
        "All inputs use UTF-8",
        "an object or an array of objects (including {} or [])",
        "JSONL uses one object per nonblank line",
        "duplicate object keys and non-finite numbers",
        "CSV requires nonempty, unique headers",
        "every row must have the same width",
        "Text has no record schema",
        "do not enforce business field presence, types, ranges, or object-versus-array semantics",
        "Synthetic inputs need not match private row counts",
        "field descriptions are not an executable schema",
    ):
        assert statement in prompt
