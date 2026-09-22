# Current Stage — Stage 7: Replayable DemoRecipe

## Goal

Persist a portable, non-sensitive recipe for each verified run and replay that
recipe through the existing deterministic pipeline only after an explicit,
machine-readable compatibility check.

## Required Outcomes

1. `DemoRecipe` is a strict versioned model containing the canonical DemoSpec,
   its SHA-256 fingerprint, fixed execution profile, compatibility requirements,
   and source-run provenance.
2. Recipe provenance references the verified execution report and final video
   by their manifest hashes; it never contains credentials, environment values,
   browser storage, API keys, or unredacted logs.
3. Recipes are created only from `PASSED`, integrity-checked runs whose spec and
   manifest identities agree.
4. `demo_recipe.json` is atomically written and integrity-recorded in the final
   artifact manifest for every successful standard run and replay.
5. Compatibility checks are deterministic and report all unsupported recipe,
   DemoSpec, report/manifest schema, engine version, and execution-profile
   constraints before browser execution.
6. `proofdemo replay RECIPE --artifacts ...` writes a versioned replay preflight
   report. Incompatible or tampered recipes never start a browser.
7. Compatible replay delegates to the existing execution, verification,
   capture, render, and optional narration services; it does not create a
   parallel executor.
8. Replay artifacts record the source recipe ID/run and the compatibility
   decision, then emit a new run ID and a new recipe with fresh provenance.
9. Narration remains explicitly opt-in during replay; a recipe never silently
   initiates a billable speech request.
10. Tests cover round-trip stability, fingerprint tampering, incompatible
    versions/profiles, source-manifest tampering, browser non-execution on
    preflight failure, successful delegation, and provenance propagation.
11. Existing planning, execution, verification, media, lint, type, and frontend
    checks continue to pass.

## Acceptance Criteria

A verified Todo run must produce `demo_recipe.json` whose embedded DemoSpec
round-trips without change and whose fingerprint and source artifact hashes are
valid. Replaying it against the fixture must create a distinct `PASSED` run,
retain the original source run in `replay_preflight.json`, and produce another
valid recipe and artifact manifest.

Changing the embedded spec without updating its fingerprint, requiring an
unsupported engine/schema/profile, or replaying a malformed recipe must produce
an explicit incompatible/invalid result before Playwright is constructed.

## Not Included

- UI change comparison, selector diagnosis, automated repair, scene repair, or
  partial rerendering;
- stored credentials, browser sessions, environment snapshots, provider keys,
  queue/worker infrastructure, cloud storage, or scheduled replay;
- guarantees that external application state is unchanged between runs.

## Completion Status

`COMPLETE`
