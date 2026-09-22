# Current Stage — Stage 8: Deterministic UI Change Detection

## Goal

Compare a replay with its integrity-verified successful baseline and identify
which stable actions, assertions, observations, or scene assumptions changed.
Diagnosis must remain evidence-based and must not repair or reinterpret failure.

## Required Outcomes

1. Baseline loading verifies the source `execution_report.json` SHA-256 against
   the recipe provenance before Playwright starts.
2. Baselines must be `PASSED`, match the recipe's source run/spec identities,
   and contain only the existing strict ExecutionReport schema.
3. Replay comparison uses stable scene/action/assertion IDs rather than array
   positions, screenshots, visual similarity, or model judgment.
4. A versioned `ui_change_report.json` distinguishes `UNCHANGED` and `CHANGED`
   and records baseline/replay run IDs, counts, and structured findings.
5. Findings classify broken selectors, failed actions, failed/missing
   assertions, changed observations, and broken scene assumptions with their
   stable correlation IDs and bounded evidence.
6. Identical successful replay produces zero findings. A failed replay still
   persists its change report and includes it in that run's artifact manifest.
7. `proofdemo replay` automatically uses the recipe directory as the baseline
   artifact directory; `--baseline-artifacts` may explicitly override it.
8. A missing implicit baseline preserves portable replay but clearly reports
   that comparison was unavailable. An explicit missing/tampered baseline is an
   invalid input and never starts a browser.
9. Change detection is read-only diagnosis. It does not alter DemoSpec,
   locators, verification status, footage, recipes, or run lifecycle.
10. Tests cover unchanged replay, changed observation, broken selector/action,
    missing result, baseline hash/identity mismatch, unavailable portable
    baseline, browser non-execution on invalid provenance, and manifest linkage.
11. Existing planning, execution, verification, narration, recipes, lint, type,
    and frontend checks continue to pass.

## Acceptance Criteria

Replaying an unchanged Todo fixture must produce `UNCHANGED` with no findings.
Changing the fixture's observed text must retain the honest failed assertion/run
and produce a correlated assertion/observation finding. Making an action target
unavailable must produce a selector/action finding and blocked downstream
assumptions without converting the replay to success.

Tampering with the baseline report or pointing an explicit baseline option at a
missing file must stop before browser construction. Every written change report
for an executed replay must be hashed in `artifact_manifest.json`.

## Not Included

- selector suggestions, model diagnosis, automatic repairs, retries, scene
  rewrites, or partial rerendering;
- pixel-diff heuristics, OCR, screenshot embedding, or visual model calls;
- scheduled monitoring, history databases, queues, workers, alerts, or cloud
  artifact storage.

## Completion Status

`COMPLETE`
