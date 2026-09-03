# Final Candidate Runner Contract

Automatic conversational materialization accepts a regular, non-symlink Python source file ending
in `.py`. Lunar-Agent copies it to an isolated attempt workspace and invokes it without a shell:

```text
<absolute current Python executable> -I <absolute attempt candidate.py>
```

The working directory is the attempt workspace. Verified inputs appear at the same run-relative
paths under `data/raw/`. The program must finish within the configured evolution timeout, exit zero,
and write each required `AlgorithmProblemContract.outputs` path below `output/`. It may use Python's
standard library; package installation and environment discovery are outside this protocol.

The process receives a minimal environment and cannot declare its own validity. Lunar-Agent ignores
stdout as a deliverable, independently parses each output according to its declared format/fields,
rejects symlinks and oversized files, and promotes only passing bytes to the intake workspace.
