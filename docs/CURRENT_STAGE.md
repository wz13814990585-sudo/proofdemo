# Current Stage — Stage 0: Foundation

## Goal

Establish a small, maintainable ProofDemo repository foundation. Stage 0 should
make product contracts explicit and give Stage 1 a tested base; it must not
attempt autonomous demo generation.

## Required Outcomes

1. A typed backend application can start and exposes a health endpoint.
2. A typed frontend application can build and start.
3. A versioned DemoSpec domain model exists.
4. A generated, shared DemoSpec JSON Schema exists and matches the model.
5. A valid example DemoSpec passes model validation.
6. A deterministic DemoRun lifecycle accepts legal transitions and rejects
   illegal or post-terminal transitions.
7. Environment configuration has safe defaults and a documented example.
8. Repository tests and configured static checks pass.
9. Architecture documentation matches the implementation.
10. README contains complete local setup and validation instructions.

## Acceptance Criteria

The following checks must succeed from a clean local checkout after installing
the documented dependencies:

```text
python -m pytest
ruff check .
mypy backend/src
npm --prefix frontend run build
```

In addition:

- `GET /health` returns HTTP 200 with `status: "ok"`;
- `examples/demo_spec.json` validates with the DemoSpec model;
- `shared/schemas/demo_spec.schema.json` is in sync with the model;
- legal DemoRun transitions reach `PASSED`, `FAILED`, and `BLOCKED` terminal
  states in tests;
- invalid transitions raise an explicit domain error;
- backend and frontend development servers are smoke-tested locally.

## Not Included

- browser installation or automation;
- autonomous exploration or UI recovery;
- model/LLM calls and intent planning;
- assertion execution;
- trace capture or browser recording;
- narration, TTS, or video rendering;
- databases, production queues, workers, or distributed infrastructure;
- replay and repair;
- CI/CD or cloud deployment.

## Completion Status

`COMPLETE` — verified 2026-09-22.

Validation performed:

- `.venv/bin/python -m pytest` — 15 tests passed;
- `.venv/bin/ruff check .` — passed;
- `.venv/bin/mypy backend/src` — passed with no issues in 7 source files;
- `npm --prefix frontend run build` — TypeScript and Vite production build
  passed;
- live Uvicorn smoke test on `127.0.0.1:18080` — `GET /health` returned HTTP
  200 and the expected service metadata;
- live Vite smoke test on `127.0.0.1:15173` — returned the application HTML;
- `examples/demo_spec.json` and the generated schema are covered by the passing
  contract tests;
- `PASSED`, `FAILED`, and `BLOCKED` terminal transitions plus invalid and
  post-terminal transitions are covered by the passing lifecycle tests.

Ports 18080 and 15173 were used only for smoke testing because the normal API
port 8000 was already occupied by another local process. Both temporary servers
were stopped after verification.
