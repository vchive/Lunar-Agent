# Research: Algorithm Problem Contract and Evolution Strategy Boundary

## Sources inspected locally

The comparison uses only files already present under `/Users/liminghan/Documents/fm`:

1. `面经/合集/项目二-伐谋WebAgent与Workspace.md`
2. `面经/07-伐谋WebAgent对话式决策算法-模拟面试.md`
3. `面经/07-伐谋WebAgent算法实验与生产迁移-模拟面试.md`
4. `面经/06-伐谋Workspace程序演化算法-模拟面试.md`
5. `面经/10-AlphaEvolve与多岛屿种群算法-深入讲解与模拟面试.md`
6. `codesets/baidu/acg-fm/webagent/agent_configs/opencode-v2.5-base/agents/*`
7. `codesets/baidu/acg-fm/webagent/opencode/{agents,plugins,tools}`

No online repository content is required for this feature. There is no local OpenEvolve checkout;
OpenEvolve is treated as the conceptual source described by the local notes, not as an imported
dependency.

## Decision 1: Preserve one problem/evaluator contract for both evolution modes

**Decision**: The problem contract, candidate artifact convention, evaluator report, and frozen
acceptance semantics are shared. Evolution strategy is a separate, validated setting with `loop`
as the default and `population` as an opt-in mode.

**Rationale**: The local WebAgent material identifies the invariant as Generate → Execute →
Evaluate → retain best, while the Workspace material adds explicit Program, Population, Archive,
Island, Migration, and Checkpoint state. The evaluator is the environment in both cases; only the
search-state manager differs. Sharing the contract prevents two incompatible definitions of
validity and quality.

**Alternatives rejected**:

- Building two independent products would duplicate solver/evaluator rules and make results
  incomparable.
- Hiding strategy selection in a runtime adapter would couple algorithm behavior to Hermes,
  OpenCode, or another provider and violate the local runtime boundary.

## Decision 2: Use loop mode as the first executable strategy

**Decision**: Implement WebAgent-like loop first: each round uses a fresh solver context, produces
one candidate, runs the frozen evaluator, records best-so-far, and stops on budget/stagnation.

**Rationale**: A local single-user agent has interactive and cost constraints. The local notes state
that WebAgent's five-round loop is a lightweight serial search, while explicit islands can split a
fixed budget and reduce vertical search depth. Fresh contexts preserve mutation independence and
avoid passing hidden reasoning chains between rounds.

**Alternatives rejected**:

- Always-on population search adds archive, selection, migration, and checkpoint complexity before
  the basic solve/evaluate contract is proven.
- Reusing one conversational session is cheaper in context but introduces path dependence: later
  rounds tend to repeat the previous solver's assumptions rather than independently exploring.

## Decision 3: Add population mode behind the same strategy interface later

**Decision**: Population mode is feasible and planned as an opt-in long-running mode after loop
mode. It will maintain immutable candidate records, parent/inspiration references, an archive of
all evaluated candidates, a bounded active population, and optional islands. It must use the same
evaluation report and never modify the evaluator during search.

**Rationale**: The local Workspace/OpenEvolve analysis says population search is useful when the
  total budget is large enough to support selection diversity and vertical depth. It also warns
  that multiple islands without heterogeneous prompts/models/data views are merely repeated
  sampling, and that fixed-budget island splitting can underperform one larger population.

**Alternatives rejected**:

- Calling the current local worker pool a population would be incorrect: it parallelizes DAG tasks,
  not candidate programs with parentage and objective-based selection.
- Implementing multi-island before archive and evaluator invariants would make recovery and credit
  attribution ambiguous.

## Decision 4: Treat validity as a lexicographic gate before quality

**Decision**: Evaluation reports use `validity` first. Invalid candidates have zero combined score;
valid candidates may then expose normalized quality and detailed metrics. All hard constraints are
reported independently rather than short-circuited.

**Rationale**: Both the WebAgent and Workspace notes emphasize that a high-quality infeasible
solution has no business value. Frozen evaluator semantics and independent recomputation also
reduce reward hacking and solver self-report bias.

## Decision 5: Materialize a visible local role workspace, not a service plane

**Decision**: Contract-bearing runs reserve `data/raw`, `data/processed`, `solve`, `evaluate`,
`output`, and `evolution` below the run workspace and write a manifest. There is no HTTP/SSE,
queue, billing, multi-tenant control plane, or mandatory external agent installation.

**Rationale**: The v2.5 base agents make role boundaries and clean hand-offs explicit. A local
directory boundary gives the same auditability and context compression while preserving Lunar's
standalone requirement.

## Decision 6: Make the parent Agent an optional process caller

**Decision**: Expose one local run contract through the CLI and JSON output. It must work when a
person launches Lunar-Agent directly, when Codex/Hermes/OpenClaw launches it as a child process,
and when a parent launches a detached run and later resumes the durable run ID. The repository's
controller, SQLite ledger, and workspace remain authoritative in all three forms; no parent
Agent's installation, memory directory, or session protocol is imported.

**Rationale**: The product is a local algorithm agent rather than a service. Treating an adapter or
parent as optional lets Lunar be useful by itself while still composing with stronger outer agents.
The process boundary is narrower and more portable than embedding provider-specific hooks, and a
durable run ID gives a parent a safe hand-off for long-running work.

**Alternatives rejected**:

- Requiring Hermes/OpenCode/Codex as the launcher would make standalone use impossible and couple
  persistence to a user-global environment.
- Adding a second RPC/service protocol would duplicate the CLI contract and reintroduce the
  deployment, queue, and lifecycle concerns explicitly out of scope for this local product.

## Consequences

- Feature 012 can validate and persist the contract without pretending to solve a domain problem.
- Feature 013 can implement conversational clarification against the contract fields.
- Feature 014 can add data-discovery/data-cleaner and solver/evaluator runtime roles.
- Feature 015 can implement single-chain loop evolution; Feature 016 can add candidate archive and
  population selection; Feature 017 can add islands only when budget and diversity evidence justify
  them.
- Strategy comparisons must report valid rate, valid-only quality, variance, cost, and anytime
  curves under equal model, task, evaluator, and total budget conditions.
- Invocation comparisons must use the same run ledger and contract: direct, child-process, and
  detached/resumed forms are interface modes, not different agent implementations.
