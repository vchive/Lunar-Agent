# Population-first evolution data model

## Active and historical strategy identities

`ActiveEvolutionStrategy` contains exactly `population` and `openevolve`. It is used by new
contracts, active configuration, CLI construction, benchmark configuration, candidate creation,
and state writers. Omitted active strategy resolves to `population`.

`HistoricalEvolutionStrategyTag` additionally recognizes `loop` while deserializing existing
contracts, `Candidate` records, archive lines, state, result, events, and sealed effect-trial
evidence. A historical tag is descriptive only. It cannot be converted silently to population or
passed into an active state writer.

`LoopStrategy` remains an importable compatibility symbol. It owns no mutable search state. Calls
to `run()` or `resume()` fail with `loop_strategy_retired` before generator, evaluator, worker,
archive, checkpoint, or population access. Historical inspection continues through the ordinary
read-only contract/archive/result parsers.

## Verified population initialization

Feature 084 supplies an adjudicated seed batch. Its canonical projection contains:

| Field | Rule |
| --- | --- |
| `schema_version` | Version of the Feature 084 handoff contract. |
| `contract_sha256` | Must equal the active algorithm contract digest. |
| `evaluator_fingerprint` | Must equal the local exact evaluator selected for the run. |
| `admitted_candidate_ids` | Non-empty, unique, identity-derived IDs in canonical sorted order. |
| `handoff_fingerprints` | One matching source/dependency/environment/provenance fingerprint per admitted ID. |
| `receipt_digests` | One verified local evaluator receipt digest per admitted ID. |
| `rejections` | Bounded fixed-code evidence; never active population members. |

Population admission is one transaction after every manifest record has been adjudicated. Each
admitted seed becomes a `Candidate` with `strategy=population`, `generation=0`, `iteration=0`,
`parent_id=null`, and an island derived from its position in the sorted admitted ID list modulo the
configured island count. `producer_run_id` remains provenance and does not determine candidate ID.
An empty admitted set creates no candidate, archive append, active ID, or formal iteration. An
admitted set larger than `population_size` is rejected before active-state mutation rather than
being silently trimmed.

The optional generic-evolve import request contains `seed_manifest`, `seed_dependency_sha256`, and
`seed_environment_sha256`, plus an explicit local exact evaluator command. The two lowercase
SHA-256 identity values are required exactly when the manifest is present and are forbidden on
their own. The canonical algorithm contract supplies `contract_sha256`; the selected evaluator
command supplies `evaluator_fingerprint`; the admission evaluator kind is exactly `exact_harness`.
All four current identities must match the manifest before source staging. The request is valid
only for population and is not a field in staged Master→Build or benchmark requests. Agent,
portfolio, and model-backed runtime evaluators cannot admit an external seed merely by claiming the
exact-harness label.

## Active population and iteration outcome

The existing `PopulationState` remains canonical for iteration, active island IDs, best candidate,
stagnation, RNG seed, and migration watermark. Active IDs may reference only locally admitted or
locally evaluated candidates. Resume rehashes the Feature 084 material and rejects a changed
contract, evaluator, source, dependency/environment, or handoff fingerprint before selection.

Each attempted offspring receives one controlled outcome before iteration accounting:

- `evaluated`: generation completed and the evaluator returned a valid structured report; the
  report may still have `validity=0`;
- `candidate_failed`: generation or candidate persistence failed with bounded evidence;
- `evaluator_timeout`: the configured evaluator did not return within its bound;
- `worker_unknown`: completion cannot be reconciled without inventing a result;
- `run_failed`: the enclosing evolution operation failed before a narrower outcome was durable.

A formal population iteration advances only after every configured offspring attempt for that
iteration has a durable outcome and at least one outcome is `evaluated`. A batch containing only
candidate, evaluator, worker, or enclosing-run failures records bounded failure evidence without
being reported as a completed formal iteration. Initialization failures remain iteration 0.
Invalid evaluated candidates may remain diagnostic archive records when existing policy permits,
but never become best or an active verified seed.

## External OpenEvolve result

An OpenEvolve result is an external material record, not an `EvaluationReport`. Its source and
framework-neutral provenance enter the Feature 084 adapter with `origin_kind=external`. Any
external score becomes only `score_present=true` inside a digest-only evidence summary; external
metadata receives the same `{present, score_present, payload_sha256}` projection. Only a matching
local exact evaluator receipt permits creation of a stable `seed-*` canonical candidate with
`strategy=openevolve`, `generation=0`, `iteration=1`, `parent_id=null`, and `island_id=null`, ranking,
or final delivery. Completed resume reconstructs this admission from canonical source and sidecar,
reruns the local evaluator, and never reruns the producer.

## Benchmark and runtime-loop configuration

An omitted benchmark strategy list normalizes to `("population",)`. Explicit lists contain only
`population` and `openevolve`; duplicates and `loop` are rejected before workspace creation.
OpenEvolve selection requires its explicit executable and a local evaluator command.

`AgentLoopRuntime`, `--agent-loop`, and `--agent-runtime-loop` are runtime profile fields. Their
fingerprints remain part of solver/evaluator adapter identity, but they never populate the active
evolution strategy field and do not authorize historical loop execution.
