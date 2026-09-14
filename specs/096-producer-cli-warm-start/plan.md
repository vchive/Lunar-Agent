# Plan

1. Extract producer manifest preparation from existing admission, retaining error ordering and
   shared validation. Add tests showing preparation alone does not evaluate or admit anything.
2. Add the standalone Shinka export command as a thin adapter over the existing exporter.
3. Add producer-result selection to evolve, use the same exact-harness identity as seeded runs,
   derive the existing source-bundle dependency and declared-protocol environment digests, and pass
   the manifest into controller seed admission. Preserve raw options for detached launches and resume.
4. Exercise native SQLite fixture export through CLI population admission and resume, along with
   conflicting options, pinned identity/source drift and no-execution export behavior.
5. Complete independent review, full/static/build/Specify/sealed validation, update README,
   architecture, roadmap and HANDOFF, and commit locally without pushing.
