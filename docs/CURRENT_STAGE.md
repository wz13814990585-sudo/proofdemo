# Current Stage — Stage 9: Bounded Scene Repair and Partial Rerender

## Goal

Turn a verified UI-change diagnosis into a narrow, review-required target repair,
prove the repaired DemoSpec in a fresh run, and reuse baseline footage for every
scene that was not invalidated.

## Required Outcomes

1. A strict versioned repair proposal may replace only typed element targets on
   existing `click`/`fill` actions or `element_visible`/`text_contains`
   assertions in exactly one diagnosed scene.
2. Repairs cannot add/remove/reorder scenes, actions, or assertions; change
   IDs/types, URLs, fill values, timeouts, expected values, goals, or source
   origin; or contain credentials/executable code.
3. `RepairService` depends on a narrow `RepairPort`. The OpenAI adapter makes
   one structured-output call with an explicit model, no tools, no persistence,
   and no execution capability.
4. Proposal input is an integrity-checked Stage 8 change report belonging to the
   supplied recipe. Candidates are deterministically revalidated and rejected
   for unrelated, duplicate, unchanged, or unsupported replacements.
5. `proofdemo propose-repair` writes a candidate for human review and never
   executes it. `proofdemo apply-repair` is the explicit approval boundary.
6. Applying a proposal reconstructs and fully validates a repaired DemoSpec,
   then delegates to the existing execution and verification pipeline.
7. A failed or blocked repaired run produces no repaired-success video. Partial
   composition starts only after every scene in the repaired run is `PASSED`.
8. Baseline artifacts and repaired artifacts must both pass manifest integrity;
   scene IDs must match; only the repaired scene may differ in contract.
9. A project-owned partial-render plan chooses repaired footage only for the
   invalidated scene and verified baseline footage for every other scene.
10. An FFmpeg adapter concatenates the selected ranges into
    `demo-repaired.mp4`; `partial_render.json` records source path/hash, source
    time bounds, output bounds, and scene provenance.
11. Repair proposal, partial-render plan, and repaired MP4 are included in the
    new manifest. The new recipe cites the repaired MP4 as final provenance.
12. Tests use fake repair providers/no billable calls and cover proposal scope,
    tampering, explicit approval, failed repair refusal, baseline reuse,
    invalidated-scene replacement, media properties, and artifact hashes.
13. Existing planning, execution, verification, narration, replay/change
    detection, lint, type, and frontend checks continue to pass.

## Acceptance Criteria

A two-scene fixture with one diagnosed target failure must accept a reviewed
replacement for that target, produce a fully `PASSED` repaired run, and create a
partial-render plan whose unchanged scene comes from baseline video and repaired
scene comes from the new verified video. The output remains 1920×1080, 30-fps
H.264 and all new artifacts pass manifest verification.

An out-of-scope proposal, tampered change report/baseline, unchanged target,
failed repaired assertion, or mismatched scene set must be rejected without a
repaired-success video. Proposal tests must never make a network request.

## Not Included

- DOM exploration, screenshots/model vision, autonomous retries, automatic
  approval, URL/value/expectation edits, multi-scene repair, or general editing;
- partial narration regeneration, audio splicing, captions, transitions, music,
  visual effects, queues, workers, or cloud rendering;
- benchmark suites, production auth/secrets, retention policy, monitoring, or
  deployment infrastructure (Stage 10).

## Completion Status

`COMPLETE`
