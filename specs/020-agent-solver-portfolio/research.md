# Research: Agent Solver Portfolio

## Existing seam

`AgentCandidateGenerator` already converts one `AgentAdapter` into the runtime-neutral
`CandidateGenerator` protocol. `PopulationStrategy` invokes that protocol repeatedly, while
`EvolutionConfig` and Feature 018 provide a credential-safe resume configuration snapshot.

## Decision

Add `AgentPortfolioGenerator` as a thin composition of existing generators. It keeps an ordered
tuple of explicitly registered adapters and selects one by modulo call index. The CLI accepts
repeatable command strings and computes one canonical digest over the ordered list plus shared
profile. No strategy or database changes are required.

## Alternatives considered

1. **Random adapter selection** — rejected because detached/resumed runs would not reproduce
   lineage without persisting a random stream and adapter schedule.
2. **Run every Agent and merge candidates** — rejected because it changes `CandidateGenerator`
   cardinality and budget semantics; deterministic round-robin is a bounded first increment.
3. **Make the portfolio a service/queue** — rejected because the product is local-first and does
   not need deployment infrastructure for multi-agent proposal diversity.
