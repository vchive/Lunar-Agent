# Feature 109: Multi-file candidates in native population

## Outcome

Run generated multi-file candidates through the existing population search, archive their
independent evaluation, select the best candidate and deliver all source files with the already
scored output snapshot. A helper-only improvement must change candidate identity and selection.

## Acceptance

1. An explicitly configured local bundle pipeline consumes complete generated source maps,
   invokes Features 103–108, and publishes ordinary Candidate records into the existing archive.
2. Receipt v2 binds the complete bundle and retained execution/evaluation references. Receipt v1
   bytes/digests and legacy single-file behavior remain compatible; source_sha256 still identifies
   entrypoint bytes, with an explicit separate bundle identity.
3. The existing population loop handles parents, generations, islands, selection, failed attempts,
   checkpoint and resume. Changing helper bytes or saved evaluation evidence prevents reuse.
4. A local command generator can emit multi-file drafts. Parent/inspiration context can expose all
   declared files. Producer-reported scores never replace the local evaluation report.
5. Controller integration and a bundle-specific delivery API retain the selected complete source
   bundle, declared scored outputs and evaluation report. Selection, inspection and delivery do not
   rerun candidates. The existing single-file materialization lifecycle is not reused implicitly.

## Scope

This is an explicit local population mode using the existing loop and publication machinery.
Ordinary solving stays the default. Existing OpenEvolve/Shinka SeedManifest import remains
single-file; generic envelope multi-file import and automatic agent-generated harness setup are
later integration work. No external framework/model runs or new effectiveness measurements.

Feature 108 snapshots remain evaluation-time observations. Allocated execution/evaluation attempts
are retained outside reusable candidate staging directories, including failed/uncertain attempts.
No new user attestation or repair authorization is introduced.
