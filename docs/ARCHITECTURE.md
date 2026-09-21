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

Only the frontend shell, API health surface, domain models, and test/tooling
foundation exist in Stage 0. The lower application layers are boundaries for
later stages, not implemented subsystems.

## Technology Choices

- **Python 3.11+** for backend and core product logic.
- **FastAPI** for a typed, inspectable HTTP boundary.
- **Pydantic v2** as the authoritative runtime model and JSON Schema source for
  DemoSpec.
- **React, TypeScript, and Vite** for a small, independently runnable frontend.
- **pytest** for backend/domain tests; **Ruff** and **mypy** for static checks.
- **Playwright** is the intended browser adapter beginning in Stage 1, but is
  deliberately absent from Stage 0 dependencies.
- **Remotion** is the intended deterministic render adapter in a later stage,
  but is deliberately absent from Stage 0.

## Repository Layout

```text
backend/src/proofdemo/  Python package and API
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

## DemoRun Lifecycle

Stage 0 defines this legal state graph:

```text
CREATED -> VALIDATED -> RUNNING -> PASSED
    |          |          |-----> FAILED
    |          |          `-----> BLOCKED
    |          |---------------> FAILED / BLOCKED
    `--------------------------> FAILED / BLOCKED
```

Terminal outcomes cannot transition further. The state transition function is
pure: it returns a new validated model and appends an immutable history entry.
Later stages will associate `PASSED` with structured assertion evidence; Stage
0 establishes only the lifecycle invariant.

## Configuration and Security

Configuration comes from `PROOFDEMO_` environment variables and contains no
secret defaults. The API exposes only non-sensitive service metadata. Browser
credentials, artifact redaction, and destructive-action safeguards belong to
the browser stages and must be designed before those features ship.

## Deliberate Deferrals

There is no browser runtime, planner, model call, database, queue, recorder,
narrator, TTS provider, or video renderer in Stage 0. Those are introduced only
when their roadmap stage supplies executable acceptance criteria.
