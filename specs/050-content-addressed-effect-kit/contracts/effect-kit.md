# Contract: Content-Addressed Effect Kit

Invocation:

```text
lunar-agent effect-kit <new-output-directory> \
  --case KEY=/absolute/private-case-root [--case KEY=/absolute/private-case-root] \
  [--benchmark-name famou-bench] \
  [--profile-name famou-agentco-default] [--profile-revision 1] \
  [--owner-attested-content-equivalence]
```

The command accepts exactly one or two unique safe case keys. Every private root is fully validated
and content-addressed, but only `instruction.md` and direct `data/*` files are copied into the kit.
The output path must not already exist. JSON output reports bounded derived identities and relative
projection paths; it never prints or persists the private source roots.
