# Feature 110 data model

## Generator configuration

`AgentCandidateGenerator(..., bundle_pipeline=pipeline)` explicitly selects complete bundle
generation. The pipeline remains the fixed local execution/evaluation profile from Feature 109.
Legacy single-file inputs/scoring helpers are not used to stage a bundle generation workspace.
No Candidate, receipt, archive or database schema changes are needed.

## Generation context

Each invocation allocates a new private directory under the run's Agent generation area. The full
`context/context.json` uses protocol `lunar-agent-bundle-generation-v1` and includes:

| Field | Content |
| --- | --- |
| `iteration` | Current population iteration |
| `contract` | Complete algorithm problem contract |
| `inputs` | Logical target, staged context path, size and SHA-256 descriptors |
| `execution` | Candidate command, cwd, output contract and `LUNAR_CANDIDATE_INPUT_ROOT` convention |
| `evaluator` | Fixed kind, evaluator ID and fingerprint; no implementation bytes |
| `parent` | Verified candidate summary and complete source references, or null |
| `archive`, `inspirations` | Bounded verified candidate summaries and local score feedback |
| `experiment_memory`, `search_directive`, `algorithm_playbook` | Existing search guidance |

The parent's `source.files_path` references `context/parent/files.json`, a complete `{path: text}`
map. `source.root` references the individual files at `context/parent/source/`; a bundle manifest
and descriptor table bind the map. Individual inline excerpts may be shortened, but the full map
and source files remain accessible. Declared input bytes live at `context/inputs/<target>`.

The prompt remains at most 60 KiB and points to full context when inline data is too large.
Generation checks original evidence and staged bytes, so a modified input or helper cannot become
trusted feedback. The evaluator implementation/private evaluation tree is not staged. This is a
context boundary, not an OS sandbox for an arbitrary local command.

## Worker response

Bundle mode requires one strict JSON object:

```json
{
  "entrypoint": "solve/main.py",
  "files": {
    "solve/main.py": "from helper import choose\n",
    "solve/helper.py": "def choose(): return 7\n"
  },
  "metadata": {"family": "example"}
}
```

`metadata` and the existing `experiment` declaration are optional. Plain source, mixed legacy
source/filename fields, duplicate keys, invalid paths or a missing entrypoint are rejected. The
existing 1 MiB AgentResult text bound applies before CandidateDraft's source/bundle validation;
this Agent response protocol does not support the full 16 MiB bundle upper bound in one response.
The worker's score claims are ordinary producer data; only the independent evaluator can score.

CommandAgentAdapter preserves the direct object's raw JSON for strict downstream parsing. A
normal AgentResult envelope with the object encoded in `text` also works. RuntimeAgentAdapter
continues to pass RuntimeResult text through the existing AgentResult boundary.

## CLI identity and recovery

`evolve-bundle` selects exactly one of `--generator-command`, `--agent-command`, `--agent-runtime`.
Existing request-file generator identity is unchanged. Agent command and native runtime identities
include distinct mode tags; native runtime selection includes model/endpoint and optional loop
settings using the existing credential-free fingerprint scheme. Runtime/Agent options are rejected
when unused, and all configuration validates before home/Store initialization or generation.

Terminal resume uses the same contract, profile, generation mode and configuration. It verifies
existing evidence without invoking a worker or candidate. Fresh workspace allocation covers an
actual new generation; an unknown pending population attempt retains its existing recovery rules
and is not authorized to replay merely by constructing a new Agent generator.
