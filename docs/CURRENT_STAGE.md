# Current Stage — Stage 1: Deterministic Browser Execution

## Goal

Execute a manually authored DemoSpec `1.1` against a deterministic local web
application through a small Playwright adapter. Produce a lightweight execution
report and explicitly requested screenshots without making any verification
claim.

## Required Outcomes

1. An application-level `ExecutionService` depends on a narrow `BrowserPort`,
   not directly on Playwright.
2. A Playwright adapter implements same-origin `goto`, typed-target `click` and
   `fill`, bounded `pause`, and requested `screenshot` actions.
3. Actions execute in DemoSpec order and produce ordered action results keyed
   by `scene_id/action_id`.
4. Successful action completion transitions DemoRun to `EXECUTED`, never
   `PASSED`.
5. Action failures produce `FAILED`; unavailable browser infrastructure
   produces `BLOCKED`. Both include explicit reasons.
6. An `ExecutionReport` records run state, ordered action results, requested
   screenshot paths, and `verification_status: NOT_RUN`.
7. A `proofdemo run` CLI validates the spec, creates an artifact directory,
   executes it, writes `execution_report.json`, and returns a meaningful exit
   code.
8. A separate deterministic Todo fixture application supports the example and
   integration tests.
9. Unit tests use a fake BrowserPort; integration tests exercise the real
   Playwright adapter and Chromium.
10. Existing Stage 0.1 contracts and tests continue to pass.

## Acceptance Criteria

Given the local Todo fixture and `examples/demo_spec.json`, running:

```text
proofdemo run examples/demo_spec.json --artifacts artifacts/todo-demo
```

must produce:

- process exit code `0`;
- `artifacts/todo-demo/execution_report.json`;
- `artifacts/todo-demo/task-created.png`;
- report status `EXECUTED`;
- verification status `NOT_RUN`;
- ordered successful results for `goto`, `fill`, `click`, and `screenshot`;
- no assertion results and no `PASSED` state.

Automated tests must also prove that:

- all typed locator strategies map through the BrowserPort contract;
- a missing target becomes `FAILED` with a non-empty reason;
- browser startup failure becomes `BLOCKED` with a non-empty reason;
- browser resources close after success and failure;
- path traversal cannot escape the requested artifact directory;
- the existing DemoSpec, DemoRun, configuration, API, and schema tests pass.

The full validation suite is:

```text
python -m pytest
ruff format --check .
ruff check .
mypy backend/src
npm --prefix frontend run build
```

## Not Included

- assertion execution, assertion results, verification evidence, or `PASSED`;
- autonomous exploration, locator repair, retries, or model calls;
- full execution trace, automatic evidence screenshots, browser video, or
  artifact manifest;
- narration, TTS, video composition, persistence, queues, or workers;
- production authentication or credential injection.

## Completion Status

`COMPLETE`
