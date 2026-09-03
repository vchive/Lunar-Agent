# Research: one-shot artifact envelope

## Decision 1 — Parse at the explicit runtime boundary

Only `OpenAICompatibleRuntime` needs a response-to-file bridge. Keeping it there avoids teaching
the controller about provider response shapes and leaves subprocess/Agent adapters free to use
their native filesystem behavior.

## Decision 2 — Require the artifacts member to opt in

Compiler responses and ordinary JSON answers must continue to be returned as text. An object is
treated as an artifact envelope only when it declares `artifacts`; malformed envelope members then
fail closed rather than silently becoming prose.

## Decision 3 — Reuse downstream contracts

The envelope can create a file, but it cannot mark it valid. `output_valid`, role-evidence rules,
artifact hashing, retry, and delivery remain unchanged and continue to decide whether the file is
usable.
