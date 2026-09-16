# Feature 109 data model

## Candidate and receipt compatibility

`CandidateDraft.source_files` is an optional complete UTF-8 source map. `filename` names an entry
in that map and `source` must equal its exact content. `CandidateDraft.from_files(files, entrypoint,
metadata=None)` constructs it. Bundle paths and aggregate byte limits reuse Feature 102. Source
names cannot collide with archive record/receipt metadata. No helper file is inferred from imports.

`Candidate.source_sha256` still hashes only entrypoint bytes. `bundle_evidence` is optional and is
omitted from legacy Candidate JSON. For bundles it has exactly these fields:

| Field | Meaning |
| --- | --- |
| `protocol` | `lunar-population-bundle-v1` |
| `bundle_sha256` | Canonical complete source bundle digest |
| `bundle_path` | Workspace-relative candidate `bundle-manifest.json` |
| `source_root` | `evolution/candidates/<candidate_id>` |
| `run_root` | Unique `evolution/bundle-attempts/.bundle-run-<nonce>` |
| `plan_sha256` | Saved workspace plan digest |
| `admission_sha256` | Saved execution admission digest |
| `completion_sha256` | Feature 107 successful recorded completion digest |
| `evaluation_path` | Evaluation directory below this run root |
| `evaluation_sha256` | Feature 108 evaluation manifest digest |

Receipt schema 2 includes this binding in its canonical payload; the ordinary integrity projection
also includes `bundle_evidence_sha256`. Schema 1 payload shape and digest are unchanged. A bundle
record must bind a v2 receipt, complete source map, successful execution, pinned evaluator report and
matching run authority. Reusing a run root or evaluation path for a different candidate ID is rejected.
Ordinary seed manifests remain single-file and cannot silently discard a source map.

## Explicit pipeline profile

`load_bundle_pipeline(path)` accepts an exact JSON object with:

```text
schema_version = "1"
protocol = "lunar-bundle-pipeline-v1"
evaluator = CandidateEvaluationSpec.to_dict()
harness_path, input_root
inputs = array of CandidateExecutionInput.to_dict()
command = explicit argv array
environment = explicit environment object
timeout_seconds, max_output_bytes
dependency_sha256, environment_sha256
```

Relative harness/input paths resolve against the profile directory. Parsing preflights the actual
pinned input/harness bytes without creating state. The runner fingerprint includes argv, explicit
environment, process limits and complete input descriptors. Evaluator/dependency/environment pins
join the existing evolution config and integrity authority. Candidate generation cannot mutate the
contract or profile and then launch using stale authority. These declarations do not authenticate
the host interpreter or dependency closure.

Command generator requests retain the existing iteration, parent, inspiration and archive fields.
For a bundle parent, `parent_source_files` adds the complete verified map. Responses may use
`{"entrypoint": "solve/main.py", "files": {"solve/main.py": "...", "solve/helper.py": "..."},
"metadata": {...}}`. Scores in generated code or metadata are never local evaluation authority.

## Retained execution and archive state

```text
evolution/
  candidates/<id>/bundle-manifest.json
  candidates/<id>/<declared source files and ordinary record/receipt sidecars>
  bundle-attempts/.bundle-run-<nonce>/
    plan.json, admission.json
    workspaces/.candidate-workspace-<nonce>/
    inputs/.candidate-inputs-<nonce>/
    attempt/
    evaluations/.candidate-evaluation-<nonce>/
  archive.jsonl, offspring-outcomes.jsonl, state.json, result.json
```

Attempt roots are retained even when staging is discarded or an operational failure prevents
candidate publication. Publication reuses the original archive transaction and unknown-publication
semantics. Existing pending outcomes/unknown publication do not authorize replay. Terminal resume
validates complete saved evidence and returns the prior result without generation or execution.

## Portable delivery

`LocalController.deliver_bundle_evolution` verifies the successful run's canonical selection against
Store artifact rows and events before allocating `.bundle-delivery-<nonce>` in an existing destination.
The destination cannot be inside the run's evolution evidence tree. `delivery.json` contains protocol
`lunar-bundle-delivery-v1`, schema 1, `observation: evaluation-time`, candidate/contract/bundle/receipt/
evaluation identity and per-file size/SHA-256 descriptors. Files are:

- `source/<all declared source paths>` and `source-bundle.json`;
- original declared `output/...` and `inputs/<target>`;
- `evaluation/report.json`, `evaluation/evaluator.py`, `evaluation/spec.json`, `contract.json`.

At most 165 files cover 64 sources, 64 inputs, 32 outputs and five supporting files; manifest bounds
allow their full declared paths. Inspection verifies bytes and the exact inventory, optionally against
a saved delivery digest, without Store initialization or any process launch. Copies may be relocated;
retained inode-bound execution/evaluation evidence is not relocated or reinterpreted as portable.
