# Research: Built-in Algorithm Role DAG

The current scheduler already provides durable dependency ordering and bounded artifact previews,
so specialist roles should be represented as ordinary `PlanTask` nodes rather than new worker
types. This preserves the adapter-neutral design and lets a future Feature 026 route the `solver`
or `evaluator` node to an Agent/evolution backend without changing intake.

The five roles are intentionally linear for the first implementation. Parallel discovery or solver
portfolios can be added later once their artifact merge and conflict semantics are specified.
