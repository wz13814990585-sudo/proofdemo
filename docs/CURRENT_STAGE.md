# Current Stage — Stage 0.1: Execution Contract Hardening

## Goal

Stabilize ProofDemo's domain and local-development contracts before any browser
runtime consumes them. This stage corrects verification semantics, identity,
target typing, time handling, configuration, and roadmap boundaries discovered
during the Stage 0 architecture review.

Stage 0.1 must not install Playwright or implement browser execution.

## Required Outcomes

1. `EXECUTED` means browser actions completed without claiming verification.
2. `PASSED` remains reserved for a future verifier and has no legal incoming
   transition in the current implementation.
3. DemoSpec schema version `1.1` provides stable Scene, Action, and Assertion
   identities, and validates their uniqueness.
4. Element targets use strategy-specific typed models rather than overloaded
   `value` and `name` fields.
5. Fixed-duration pacing is explicitly represented as `pause`; it is not a
   page-readiness mechanism.
6. `source_url` defines the allowed Stage 1 origin, the first action is an
   explicit navigation, and every navigation remains on that origin.
7. DemoRun timestamps are timezone-aware, normalized to UTC, and invalid time
   input raises an explicit domain error.
8. `.env` configuration is actually loaded, and documented frontend/backend
   defaults use the same origin spelling.
9. Stage 1 requested screenshots and lightweight execution results are clearly
   separated from Stage 3 automatic capture and full trace persistence.
10. Documentation, examples, generated schema, and tests agree with the
    hardened contracts.

## Acceptance Criteria

The following checks must succeed:

```text
python -m pytest
ruff format --check .
ruff check .
mypy backend/src
npm --prefix frontend run build
```

The test suite must also demonstrate that:

- a run can reach `EXECUTED`, `FAILED`, and `BLOCKED` as appropriate;
- no current transition can produce `PASSED`;
- naive timestamps are rejected with a domain error;
- duplicate Scene, Action, and Assertion IDs are rejected;
- invalid target field combinations are rejected;
- cross-origin navigation and a missing initial navigation are rejected;
- the checked-in DemoSpec example validates as schema version `1.1`;
- the shared JSON Schema is in sync;
- `.env` values load and real environment variables take precedence;
- the documented frontend origin passes the API's CORS preflight;
- the Git worktree contains no Playwright dependency or browser executor.

## Not Included

- Playwright or any other browser engine;
- browser execution services or adapters;
- assertion execution or verification evidence generation;
- trace capture, automatic screenshots, recording, or artifact manifests;
- LLM planning, narration, TTS, or rendering;
- databases, workers, queues, or deployment infrastructure.

## Completion Status

`COMPLETE` — verified 2026-09-22.

Validation performed:

- `.venv/bin/python -m pytest` — 32 tests passed;
- `.venv/bin/ruff format --check .` — 18 files already formatted;
- `.venv/bin/ruff check .` — passed;
- `.venv/bin/python -m mypy backend/src` — passed with no issues in 7 source
  files;
- `npm --prefix frontend run build` — TypeScript and Vite production build
  passed;
- generated DemoSpec schema `1.1` matches the authoritative model;
- live Uvicorn smoke test on `127.0.0.1:18080` returned the expected health
  response;
- live CORS preflight from `http://127.0.0.1:15173` returned HTTP 200 with the
  matching `access-control-allow-origin` header;
- live Vite smoke test on `127.0.0.1:15173` returned the application HTML;
- a source/dependency scan confirmed no Playwright or browser-executor
  implementation was introduced;
- `git diff --check` passed.

Alternate ports 18080 and 15173 were used only for smoke testing. Both
temporary servers were stopped after verification.
