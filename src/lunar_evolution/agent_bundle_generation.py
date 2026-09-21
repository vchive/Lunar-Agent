"""Verified multi-file generation context for the existing Agent candidate adapter."""
from __future__ import annotations

import hashlib
import json
import os

from . import _benchmark_files as files
from ._candidate_workspace_io import DirectoryChain, PrivateTree
from .agents import (
    BUNDLE_RESPONSE_PROTOCOL,
    MAX_TEXT_BYTES,
    AgentError,
    AgentRequest,
    AgentResult,
    candidate_failure_reason,
    candidate_model_failure_cause,
)
from .algorithm import ALGORITHM_FAMILY_REPERTOIRES, AlgorithmProblemContract
from .automatic_solve_lifecycle import SolveExecutionBudgetExceeded, SolveExecutionCancelled
from .bundle_evolution import read_candidate_source_files, validate_candidate_bundle_evidence
from .candidate_bundle import MAX_CANDIDATE_TOTAL_SOURCE_BYTES
from .candidate_evaluation import _close, _Observation, _Resources
from .candidate_evaluation_spec import canonical_json, strict_json
from .evolution import (
    MAX_ARCHIVE_BYTES,
    MAX_ARCHIVE_LINE_BYTES,
    MAX_STATE_BYTES,
    CandidateArchive,
    CandidateDraft,
    CandidateIntegrityAuthority,
    CandidateReceipt,
    EvolutionError,
    _canonical_sha256,
    _sanitized_evaluation,
    _validate_ordinary_metadata,
)

_PROTOCOL = BUNDLE_RESPONSE_PROTOCOL
_MAX_CONTEXT_BYTES = 2 * 1024 * 1024
_MAX_MAP_BYTES = MAX_CANDIDATE_TOTAL_SOURCE_BYTES * 6 + 128 * 1024


def _fail(code="invalid"):
    raise EvolutionError("agent_bundle_generation_" + code)


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def bundle_generator_identity(pipeline, contract):
    """Pin the contract and scoring/execution profile without exposing evaluator source."""
    return {
        "contract_sha256": contract.digest(),
        "evaluator_kind": pipeline.evaluator.pin().kind,
        "evaluator_fingerprint": pipeline.evaluator.digest(),
        "dependency_sha256": pipeline.dependency_sha256,
        "environment_sha256": pipeline.environment_sha256,
        "runner_fingerprint": pipeline.runner_fingerprint,
    }


def parse_bundle_agent_draft(text, *, adapter_name):
    from .agent_evolution import _normalize_experiment

    try:
        payload = strict_json(text, maximum=MAX_TEXT_BYTES)
        if (not isinstance(payload, dict) or not {"entrypoint", "files"} <= set(payload)
                or set(payload) - {"entrypoint", "files", "metadata", "experiment"}):
            _fail("response_invalid")
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict) or "experiment" in metadata or "agent_adapter" in metadata:
            _fail("response_invalid")
        metadata = {**metadata, "agent_adapter": adapter_name}
        if "experiment" in payload:
            metadata["experiment"] = _normalize_experiment(payload["experiment"])
        metadata = _validate_ordinary_metadata(metadata)
        return CandidateDraft.from_files(payload["files"], payload["entrypoint"], metadata)
    except (TypeError, ValueError, KeyError, UnicodeError, RecursionError):
        _fail("response_invalid")


def _archive_view(workspace):
    """Read the active population without invoking seed recovery or creating archive state."""
    archive = CandidateArchive.__new__(CandidateArchive)
    archive.workspace = workspace
    archive.root = workspace / "evolution"
    archive.candidates_root = archive.root / "candidates"
    archive.archive_path = archive.root / "archive.jsonl"
    archive.state_path = archive.root / "state.json"
    archive.offspring_outcomes_path = archive.root / "offspring-outcomes.jsonl"
    return archive


def _candidate_payload(candidate):
    value = candidate.to_dict()
    value["evaluation"] = _sanitized_evaluation(candidate.evaluation).to_dict()
    return value


def _authority(archive, records, identity):
    state = archive.read_state()
    raw = state.get("candidate_integrity_authority")
    if raw is None and records:
        projection = records[0].integrity or {}
        raw = {name: projection.get(name) for name in CandidateIntegrityAuthority.__dataclass_fields__}
    if raw is None:
        return None
    authority = CandidateIntegrityAuthority.from_dict(raw)
    if any(getattr(authority, name) != value for name, value in identity.items()):
        _fail("authority_mismatch")
    return authority


def _verify_candidate(archive, candidate, authority):
    """Verify displayed evidence; population retains ownership of journal/lineage decisions."""
    if candidate.bundle_evidence is None or authority is None:
        _fail("parent_invalid")
    receipt = archive.read_candidate_receipt(candidate.candidate_id, candidate.code_path)
    authority_fields = authority.to_dict()
    authority_fields.pop("schema_version")
    expected = CandidateReceipt.from_report(
        candidate.evaluation, candidate_id=candidate.candidate_id,
        source_sha256=candidate.source_sha256, parent_id=candidate.parent_id,
        generation=candidate.generation, iteration=candidate.iteration, island_id=candidate.island_id,
        execution_sha256=receipt.execution_sha256, bundle_evidence=candidate.bundle_evidence,
        **authority_fields,
    )
    projection = {
        **authority.to_dict(), "candidate_id": candidate.candidate_id, "parent_id": candidate.parent_id,
        "generation": candidate.generation, "iteration": candidate.iteration, "island_id": candidate.island_id,
        "receipt_sha256": receipt.receipt_sha256, "source_sha256": candidate.source_sha256,
        "bundle_evidence_sha256": _canonical_sha256(candidate.bundle_evidence),
    }
    source = archive.workspace / candidate.code_path
    raw_record = files.read_regular_file(source.parent / "record.json", MAX_ARCHIVE_LINE_BYTES)
    if (receipt != expected or receipt.receipt_sha256 != candidate.receipt_sha256
            or projection != candidate.integrity
            or strict_json(raw_record, maximum=MAX_ARCHIVE_LINE_BYTES) != candidate.to_dict()
            or _sha(files.read_regular_file(source, 512 * 1024)) != candidate.source_sha256):
        _fail("parent_invalid")
    validate_candidate_bundle_evidence(
        archive.workspace, candidate.bundle_evidence, code_path=candidate.code_path,
        evaluation=candidate.evaluation, authority=authority,
    )


def _verify_request(generator, request, workspace):
    pipeline = generator.bundle_pipeline
    identity = bundle_generator_identity(pipeline, generator.contract)
    if identity != generator._bundle_identity:
        _fail("profile_changed")
    pipeline.preflight()
    contract = AlgorithmProblemContract.from_dict(generator.contract.to_dict())
    archive = _archive_view(workspace)
    contract_path = archive.root / "contract.json"
    if contract_path.exists() or contract_path.is_symlink():
        saved = AlgorithmProblemContract.from_dict(strict_json(
            files.read_regular_file(contract_path, 512 * 1024), maximum=512 * 1024,
        ))
        if saved.digest() != contract.digest():
            _fail("contract_changed")
    records = archive.records()
    if [_candidate_payload(item) for item in request.archive] != [item.to_dict() for item in records]:
        _fail("archive_changed")
    by_id = {item.candidate_id: item for item in records}
    displayed = [*records[-8:], *request.inspirations[:8]]
    if request.parent is not None:
        displayed.append(request.parent)
    authority = _authority(archive, records, identity)
    selected = {}
    for requested in displayed:
        candidate = by_id.get(requested.candidate_id)
        if candidate is None or _candidate_payload(requested) != candidate.to_dict():
            _fail("parent_invalid")
        if candidate.candidate_id not in selected:
            _verify_candidate(archive, candidate, authority)
            selected[candidate.candidate_id] = candidate
    return archive, contract, selected


def _generation_parent(workspace):
    """Create only fixed ancestors through held descriptors; allocate a fresh random leaf later."""
    chain = DirectoryChain(workspace, "agent_bundle_generation_workspace_invalid")
    path = workspace
    try:
        for name in ("evolution", "agent", "bundle-generations"):
            try:
                os.mkdir(name, 0o700, dir_fd=chain.fd)
                os.fsync(chain.fd)
            except FileExistsError:
                pass
            following = DirectoryChain(path / name, "agent_bundle_generation_workspace_invalid")
            try:
                chain.close()
            except BaseException:
                following.close()
                raise
            chain = following
            path /= name
        return path, chain
    except BaseException:
        chain.close()
        raise


def _context(generator, request, contract, selected, sources):
    from .agent_evolution import (
        _algorithm_playbook,
        _bounded_evidence_text,
        _candidate_summary,
        _experiment_memory,
        _search_directive,
    )

    pipeline = generator.bundle_pipeline
    memory = _experiment_memory(request.archive, retained_tags=ALGORITHM_FAMILY_REPERTOIRES.get(contract.problem_type, ()))
    directive = _search_directive(request, memory)
    parent = selected.get(request.parent.candidate_id) if request.parent is not None else None
    parent_summary = _candidate_summary(parent)
    if parent is not None:
        parent_summary["source"] = {
            "files_path": "context/parent/files.json", "root": "context/parent/source",
            "manifest_path": "context/parent/bundle.json", "bundle_sha256": parent.bundle_evidence["bundle_sha256"],
            "file_count": len(sources), "total_bytes": sum(len(text.encode("utf-8")) for text in sources.values()),
            "files": [{"path": name, "size": len(text.encode("utf-8")), "sha256": _sha(text.encode("utf-8")),
                       "excerpt": _bounded_evidence_text(text, 2048), "truncated": len(text.encode("utf-8")) > 2048}
                      for name, text in sorted(sources.items())],
        }
    return {
        "protocol": _PROTOCOL, "iteration": request.iteration, "contract": contract.to_dict(),
        "inputs": [{"path": item.target, "context_path": "context/inputs/" + item.target,
                    "size": item.size, "sha256": item.sha256} for item in pipeline.inputs],
        "execution": {"input_root_env": "LUNAR_CANDIDATE_INPUT_ROOT", "cwd": ".",
                      "command": list(pipeline.command), "outputs": [item.to_dict() for item in contract.outputs]},
        "evaluator": {"kind": pipeline.evaluator.pin().kind, "evaluator_id": pipeline.evaluator.evaluator_id,
                      "fingerprint": pipeline.evaluator.digest()},
        "parent": parent_summary,
        "archive": [_candidate_summary(selected[item.candidate_id]) for item in request.archive[-8:]],
        "inspirations": [_candidate_summary(selected[item.candidate_id]) for item in request.inspirations[:8]],
        "experiment_memory": memory, "search_directive": directive,
        "algorithm_playbook": _algorithm_playbook(contract, request, memory, directive),
    }


def _prompt(context, context_bytes):
    from .agent_evolution import MAX_GENERATION_PROMPT_BYTES

    prefix = (
        "You are the solver in a bounded local multi-file algorithm evolution run. "
        "Read context/context.json for the complete verified generation context. "
        "Declared input copies are available at each inputs[].context_path while generating. "
        "The executed candidate must read its inputs from os.environ['LUNAR_CANDIDATE_INPUT_ROOT']; "
        "its cwd is the source bundle root. Preserve the exact declared output/* contract. "
        "Context files are read-only evidence; use other workspace files for scratch work. "
        "A parent has its complete source map at parent.source.files_path and every full file at "
        "parent.source.root; excerpts are previews, never the candidate identity or all source. "
        "The independent evaluator computes validity and scores; candidate or producer score claims "
        "have no authority. Its identity and verified score summaries are provided, not its private implementation. "
        "Use experiment_memory, search_directive and algorithm_playbook to choose an attributable improvement. "
        "Return only one strict JSON object with required entrypoint and files (a complete path-to-source-string "
        "map including the entrypoint), optional metadata with scalar values, and optional experiment. "
        "An experiment has schema_version='1', a nonempty hypothesis string, change_tags as a nonempty array "
        "of unique strings, and target_metrics as a nonempty array of objects with unique metric strings "
        "and direction='increase' or 'decrease'. The entire experiment may be omitted. "
        "When providing an experiment, include algorithm_playbook.family_tag in change_tags when present. "
        "Return the complete revised source map, including unchanged helpers; do not return patches, markdown, "
        "plain source, success claims or an evaluation report. The entire response must fit 1 MiB UTF-8. "
        "Candidate paths, counts and total source sizes remain bounded by the source bundle contract.\n\n"
        "The following examples demonstrate response shape only; they are not task solutions or score claims. "
        "Your complete source must still satisfy the task and output contract.\n"
        'Minimal response example:\n{"entrypoint":"main.py","files":{"main.py":"pass\\n"}}\n'
        'Optional experiment example:\n{"entrypoint":"main.py","files":{"main.py":"pass\\n",'
        '"helper.py":"value = 1\\n"},"metadata":{"family":"example"},"experiment":'
        '{"schema_version":"1","hypothesis":"A helper change may improve quality.",'
        '"change_tags":["helper"],"target_metrics":[{"metric":"quality","direction":"increase"}]}}\n\n'
        "Generation context:\n"
    )
    inline = context
    prompt = prefix + json.dumps(inline, ensure_ascii=False, sort_keys=True)
    if len(prompt.encode("utf-8")) > MAX_GENERATION_PROMPT_BYTES:
        parent = context["parent"]
        inline = {
            "protocol": _PROTOCOL, "iteration": context["iteration"],
            "context_file": {"path": "context/context.json", "size": len(context_bytes), "sha256": _sha(context_bytes)},
            "contract_file": "context/contract.json", "evaluator": context["evaluator"],
            "parent": None if parent is None else {
                "candidate_id": parent["candidate_id"], "combined_score": parent["combined_score"],
                "source": {name: parent["source"][name] for name in (
                    "files_path", "root", "manifest_path", "bundle_sha256", "file_count", "total_bytes",
                )},
            },
            "archive_count": len(context["archive"]), "inspiration_count": len(context["inspirations"]),
        }
        prompt = prefix + json.dumps(inline, ensure_ascii=False, sort_keys=True)
    if len(prompt.encode("utf-8")) > MAX_GENERATION_PROMPT_BYTES:
        _fail("context_too_large")
    return prompt


def generate_bundle_candidate(generator, request):
    pipeline = generator.bundle_pipeline
    try:
        workspace = files.absolute_path(request.workspace)
        archive, contract, selected = _verify_request(generator, request, workspace)
        parent = selected.get(request.parent.candidate_id) if request.parent is not None else None
        sources = read_candidate_source_files(workspace, parent) if parent is not None else {}
        with _Resources() as resources:
            parent_path, chain = _generation_parent(workspace)
            resources.callback(_close, chain.close)
            observed = []
            for path, maximum in ((archive.archive_path, MAX_ARCHIVE_BYTES), (archive.state_path, MAX_STATE_BYTES),
                                  (archive.root / "contract.json", 512 * 1024)):
                observed.append(_Observation(path, maximum, resources, code="context_changed", optional=True))
            harness = _Observation(pipeline.harness_path, pipeline.evaluator.harness_size, resources, code="harness_changed")
            observed.append(harness)
            if _sha(harness.content) != pipeline.evaluator.harness_sha256:
                _fail("profile_changed")
            copies = {"context/contract.json": canonical_json(contract.to_dict(), maximum=512 * 1024)}
            for item in pipeline.inputs:
                snapshot = _Observation(pipeline.input_root / item.target, item.size, resources, code="input_changed")
                observed.append(snapshot)
                if len(snapshot.content) != item.size or _sha(snapshot.content) != item.sha256:
                    _fail("input_changed")
                copies["context/inputs/" + item.target] = snapshot.content
            for name, source in sources.items():
                content = source.encode("utf-8")
                snapshot = _Observation(workspace / parent.bundle_evidence["source_root"] / name,
                                        len(content), resources, code="source_changed")
                observed.append(snapshot)
                if snapshot.content != content:
                    _fail("source_changed")
                copies["context/parent/source/" + name] = content
            if parent is not None:
                copies["context/parent/files.json"] = canonical_json(sources, maximum=_MAX_MAP_BYTES)
                copies["context/parent/bundle.json"] = files.read_regular_file(
                    workspace / parent.bundle_evidence["bundle_path"], 128 * 1024,
                )
            context = _context(generator, request, contract, selected, sources)
            copies["context/context.json"] = canonical_json(context, maximum=_MAX_CONTEXT_BYTES)
            prompt = _prompt(context, copies["context/context.json"])
            if "read_files" not in generator.adapter.capabilities:
                _fail("read_files_required")
            tree = PrivateTree(chain, prefix=".bundle-generation-")
            resources.callback(_close, tree.close)
            destination = parent_path / tree.name
            for name, content in copies.items():
                tree.write(name, content)
            tree.sync_and_check()
            staged = [_Observation(destination / name, len(content), resources, code="context_changed")
                      for name, content in copies.items()]
            if any(snapshot.content != content for snapshot, content in zip(staged, copies.values(), strict=True)):
                _fail("context_changed")
            for snapshot in [*observed, *staged]:
                snapshot.check()
            _verify_request(generator, request, workspace)
            timeout = generator._effective_timeout("candidate_generation")
            agent_request = AgentRequest(
                run_id=f"evolution-{workspace.name or 'workspace'}",
                task_id=f"generation-{request.iteration:08d}-{generator._calls:04d}", role=generator.role,
                prompt=prompt, required_capabilities=generator.required_capabilities,
                workspace=destination, timeout=timeout,
                candidate_budget=generator._request_budget(request, timeout=timeout),
                response_protocol=_PROTOCOL,
            )
            try:
                result = generator.adapter.run(agent_request)
                generator._effective_timeout("candidate_generation")
            except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
                raise
            except AgentError as exc:
                generator._effective_timeout("candidate_generation")
                if not getattr(exc, "candidate_diagnostic", None):
                    generator._emit_generation_diagnostic(
                        agent_request, reason=candidate_failure_reason(exc), phase="run",
                        failure_cause=candidate_model_failure_cause(exc),
                    )
                _fail("worker_failed")
            except Exception as exc:  # noqa: BLE001 - an external Agent failure has one fixed boundary
                generator._effective_timeout("candidate_generation")
                generator._emit_generation_diagnostic(
                    agent_request, reason=candidate_failure_reason(exc), phase="run",
                    failure_cause=candidate_model_failure_cause(exc),
                )
                _fail("worker_failed")
            if (not isinstance(result, AgentResult) or result.status != "succeeded"
                    or result.adapter_name != generator.adapter.name or result.role != generator.role):
                generator._emit_generation_diagnostic(
                    agent_request,
                    reason=("cancelled" if isinstance(result, AgentResult) and result.status == "cancelled"
                            else "worker_failed"),
                    result=result if isinstance(result, AgentResult) else None,
                    phase="run",
                )
                _fail("worker_failed")
            for snapshot in [*observed, *staged]:
                snapshot.check()
            tree.check_root()
            _verify_request(generator, request, workspace)
            try:
                draft = generator._draft(result.text)
            except EvolutionError:
                generator._emit_generation_diagnostic(
                    agent_request, reason="malformed_candidate", result=result,
                )
                raise
            generator._effective_timeout("candidate_generation")
            generator._emit_generation_diagnostic(
                agent_request,
                reason="completed",
                result=result,
                candidate_id=getattr(request, "candidate_id", None),
                source_bundle_sha256=generator._source_bundle_sha256(draft),
            )
            generator._observe_artifacts(result, destination, workspace, agent_request.task_id)
            return draft
    except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RecursionError):
        _fail("invalid")
