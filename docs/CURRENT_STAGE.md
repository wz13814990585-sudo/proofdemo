# Current Stage — Stage 2: Assertions and Verified Scenes

## Goal

Turn deterministic browser observations into explicit assertion evidence and
honest scene outcomes. A run may become `PASSED` only after every scene has at
least one assertion and every assertion passes.

## Required Outcomes

1. DemoSpec advances to schema version `1.2` and requires at least one
   assertion per scene.
2. The supported deterministic assertion set covers visible elements, text
   content, exact normalized URL, completed downloads, and an opt-in
   application-state hook.
3. The application-owned `BrowserPort` exposes narrow observation methods;
   Playwright types do not enter domain or application models.
4. Every assertion result is keyed by `scene_id/assertion_id`, records
   `PASSED`, `FAILED`, or `BLOCKED`, and contains its expected and observed
   structured evidence when an observation is available.
5. Every scene receives a `PASSED`, `FAILED`, or `BLOCKED` result. A failed
   action fails its scene; unavailable infrastructure blocks the affected and
   remaining scenes.
6. All scenes passing transitions DemoRun from `RUNNING` through `EXECUTED` to
   `PASSED`. No non-deterministic or model-produced statement can cause that
   transition.
7. A false assertion produces `FAILED`; an unavailable observation
   precondition produces `BLOCKED`. Both include explicit reasons and never
   become `PASSED`.
8. `ExecutionReport` advances to version `2.0`, contains scene and assertion
   results, and reports verification as `PASSED`, `FAILED`, `BLOCKED`, or
   `NOT_RUN` without introducing the Stage 3 trace or artifact manifest.
9. The Todo fixture and example spec exercise DOM, URL, download, and
   application-state verification against real Chromium.
10. Existing execution, configuration, API, schema, lint, type, and frontend
    checks continue to pass.

## Application-state Hook

Supported applications may explicitly expose a JSON-compatible object as
`window.__PROOFDEMO_STATE__`. An `app_state_equals` assertion reads one declared
top-level key from that object and compares it by JSON value. The spec cannot
provide JavaScript, expressions, or arbitrary property paths.

## Acceptance Criteria

Given the local Todo fixture and `examples/demo_spec.json`, running:

```text
proofdemo run examples/demo_spec.json --artifacts artifacts/todo-demo
```

must produce:

- process exit code `0`;
- a run status of `PASSED` with a legal `EXECUTED -> PASSED` transition;
- a verification status of `PASSED`;
- a `PASSED` scene result for `create_task`;
- passing `text_contains`, `element_visible`, `url_equals`,
  `download_completed`, and `app_state_equals` results;
- structured expected and observed evidence correlated to every assertion;
- the Stage 1 requested screenshot, without automatic evidence capture.

Automated tests must additionally prove that:

- one false assertion yields a failed assertion, scene, run, and CLI exit;
- observation infrastructure failure yields `BLOCKED` with a reason;
- later scenes are marked `BLOCKED` after a prior failure or block;
- an empty assertion list is rejected by DemoSpec validation;
- download success requires a completed download with the expected filename;
- the application-state assertion cannot execute arbitrary JavaScript;
- browser resources still close after every success and failure path.

The full validation suite remains:

```text
python -m pytest
ruff format --check .
ruff check .
mypy backend/src
npm --prefix frontend run build
```

## Not Included

- full immutable trace events, automatic evidence screenshots, logs, browser
  video, hashes, or an artifact manifest;
- autonomous exploration, locator repair, retries, or model calls;
- network-response assertions beyond completed browser downloads;
- credentials, cross-origin workflows, destructive actions, or production
  authentication;
- narration, TTS, video composition, recipe persistence, queues, or workers.

## Completion Status

`COMPLETE`
