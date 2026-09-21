# Quickstart

The static command copies a verified source bundle into a new private directory:

```bash
lunar-evolution candidate-bundle materialize MANIFEST \
  --source-root SOURCE_ROOT --contract CONTRACT --workspace-root WORKSPACE_ROOT --json
```

The command prints bundle and file-table digests and counts. It does not start the declared
entrypoint or initialize the Lunar home.
