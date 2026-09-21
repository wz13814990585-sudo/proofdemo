# ProofDemo Roadmap

The roadmap controls sequence, not detailed implementation. Only the stage in
`CURRENT_STAGE.md` is authorized for implementation.

## Stage 0 — Foundation (current)

Create the repository, product and architecture documentation, API/frontend
shells, authoritative DemoSpec models and schema, deterministic DemoRun
lifecycle, test infrastructure, and local setup.

## Stage 1 — Deterministic Browser Execution

Execute a manually authored DemoSpec with a Playwright adapter. Begin with
navigation, click, fill, bounded wait, and screenshot actions against a local
test application. No model planning or autonomous recovery.

## Stage 2 — Assertions and Verified Scenes

Evaluate explicit DOM, URL, download, and application-facing assertions. Give
every scene a `PASSED`, `FAILED`, or `BLOCKED` outcome tied to evidence.

## Stage 3 — Trace and Browser Recording

Persist structured action/observation events, screenshots, logs, artifact
metadata, and browser video without changing verification semantics.

## Stage 4 — Deterministic Video Composition

Transform verified traces and recordings into a repeatable timeline and basic
1080p video with deterministic composition.

## Stage 5 — Demo Planner

Use a bounded model call to turn natural-language intent into a reviewable
DemoSpec that the existing deterministic pipeline can validate and execute.

## Stage 6 — Narration and TTS

Generate narration constrained by verified events, synthesize speech, and align
audio to scene timing without inventing success claims.

## Stage 7 — Replayable DemoRecipe

Persist stable inputs and execution metadata, then replay a recipe with clear
compatibility and provenance reporting.

## Stage 8 — UI Change Detection

Compare replay observations with prior successful evidence and identify broken
selectors, assertions, or scene assumptions.

## Stage 9 — Scene Repair and Partial Rerender

Propose bounded scene repairs, require appropriate verification, and rerender
only invalidated portions of a demo.

## Stage 10 — Benchmarks and Production Hardening

Create representative evaluation fixtures, measure execution and verification
quality, harden security and operations, and add production infrastructure only
where measurements justify it.
