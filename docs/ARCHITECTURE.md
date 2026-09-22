# ProofDemo Architecture

## Current Shape

ProofDemo starts as a modular monolith with separately runnable web and API
processes:

```text
Frontend (React/TypeScript)
        |
        v
Backend API (FastAPI)
        |
        v
Application orchestration
   |       |       |
   v       v       v
Domain  Adapters  Persistence
```

Through Stage 1, the application layer contains one deterministic execution
service. It drives an application-owned browser port, whose first adapter is a
synchronous Playwright Chromium session. Assertions remain inert input data
until Stage 2.

## Technology Choices

- **Python 3.11+** for backend and core product logic.
- **FastAPI** for a typed, inspectable HTTP boundary.
- **Pydantic v2** as the authoritative runtime model and JSON Schema source for
  DemoSpec.
- **Pydantic Settings** for validated `.env` and process-environment loading.
- **React, TypeScript, and Vite** for a small, independently runnable frontend.
- **pytest** for backend/domain tests; **Ruff** and **mypy** for static checks.
- **Playwright** supplies the Stage 1 Chromium adapter behind an
  application-owned port.
- **Remotion** is the intended deterministic render adapter in a later stage,
  but is deliberately absent through Stage 0.1.

## Repository Layout

```text
backend/src/proofdemo/  Python package, API, application, ports, and adapters
frontend/               React application
shared/schemas/         generated cross-runtime contracts
examples/               checked-in valid product inputs
scripts/                deterministic developer utilities
tests/                  domain and API tests
docs/                   product and planning sources of truth
```

The Python DemoSpec models are authoritative. `scripts/export_schema.py`
exports their JSON Schema to `shared/schemas/demo_spec.schema.json`; a test
prevents the committed contract from drifting.

## Dependency Direction

The intended dependency direction is:

```text
API / CLI -> application services -> domain <- adapters
```

Domain code must not depend on FastAPI, Playwright, model SDKs, persistence, or
rendering frameworks. Adapters implement application-defined boundaries.

## Deterministic and Model-owned Work

| Concern | Owner |
| --- | --- |
| DemoSpec validation | deterministic domain code |
| Run state transitions | deterministic domain code |
| Browser actions | deterministic Playwright adapter |
| Assertions | deterministic verifier |
| Trace/artifact persistence | deterministic services |
| Video composition | deterministic render adapter |
| Intent-to-DemoSpec planning | model behind a narrow boundary |
| Ambiguous UI resolution | model-assisted, evidence recorded |
| Narration draft | model behind a narrow boundary |

## DemoSpec Execution Contract

Schema version `1.1` uses stable IDs for every Scene, Action, and Assertion.
Scene IDs are unique within a spec; Action and Assertion IDs are unique within
their Scene. Canonical correlation keys are therefore:

```text
scene_id/action_id
scene_id/assertion_id
```

Element targets are a discriminated union of role, label, text, test ID, and
CSS selector strategies. The target model for each strategy exposes only fields
that the strategy can use.

`source_url` defines the allowed origin during the first deterministic browser
stage. The first action is an explicit `goto`, and every `goto` must remain on
that origin. Cross-origin workflows require a future explicit security design.

`pause` is a bounded presentation delay. It must not be used as a substitute
for Playwright readiness or locator auto-waiting.

## Stage 1 Execution Boundary

`ExecutionService` accepts an already validated DemoSpec, a `BrowserPort`, and
an artifact directory. It executes scene actions in declared order and emits a
small `ExecutionReport` with the immutable DemoRun, ordered action results,
requested screenshot paths, and `verification_status: NOT_RUN`.

The browser port contains only `open`, `goto`, `click`, `fill`, `pause`,
`screenshot`, and idempotent `close` operations. The Playwright adapter owns
locator translation, browser lifecycle, Playwright error translation, and
runtime same-origin enforcement. The application service owns ordering,
run-state transitions, result correlation, and contained screenshot paths.

Browser startup and runtime availability errors produce `BLOCKED`. A requested
action that cannot complete produces `FAILED`. All actions completing produces
`EXECUTED`, not `PASSED`. Browser resources are closed on every path.

The Todo fixture under `examples/todo_app/` is deliberately independent of the
ProofDemo frontend. It is a deterministic execution target, not product UI.

## DemoRun Lifecycle

Stage 1 consumes this legal state graph:

```text
CREATED -> VALIDATED -> RUNNING -> EXECUTED
    |          |          |          |
    |          |          |          `-> FAILED / BLOCKED
    |          |          |------------> FAILED / BLOCKED
    |          |-----------------------> FAILED / BLOCKED
    `----------------------------------> FAILED / BLOCKED
```

`EXECUTED` means all requested browser actions completed; it is not a verified
success result. `PASSED` is reserved in the enum but has no legal incoming
transition until Stage 2 introduces deterministic verification evidence.

`PASSED`, `FAILED`, and `BLOCKED` are terminal. The state transition function
is pure: it constructs a fully revalidated model and appends an immutable
history entry. All timestamps are timezone-aware and normalized to UTC.

## Configuration and Security

Configuration comes from `.env` and `PROOFDEMO_` environment variables, with
real environment variables taking precedence. It contains no secret defaults.
The documented frontend and API defaults both use `127.0.0.1`. The API exposes
only non-sensitive service metadata. Browser navigation is constrained to the
validated source origin, screenshots cannot escape their artifact directory,
and literal fills are restricted by contract to non-sensitive demo data. Stage
1 does not support credential injection.

## Deliberate Deferrals

There is no assertion executor, verification evidence, automatic trace,
recorder, planner, model call, database, queue, narrator, TTS provider, or video
renderer through Stage 1. Those are introduced only when their roadmap stage
supplies executable acceptance criteria.
