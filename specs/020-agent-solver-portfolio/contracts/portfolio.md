# Solver Portfolio Contract

The portfolio is an ordered list of two or more explicit Feature 014 Agent commands. Each receives
the normal `AgentRequest` JSON payload and returns a candidate proposal. Selection is:

```text
adapter_index = generation_call_index mod len(adapters)
```

The selected adapter's proposal is archived and independently evaluated exactly like a single-agent
proposal. A member failure is a bounded generation error, not an evaluation pass.
