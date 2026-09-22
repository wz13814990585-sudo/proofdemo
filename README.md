# ProofDemo

ProofDemo is a verified product demo system. Its long-term goal is to turn a web
application URL and natural-language intent into a polished, replayable demo
whose important claims are backed by observable evidence.

The product flow is:

```text
Intent -> Plan -> Execute -> Verify -> Capture -> Render
```

This repository currently implements **Stage 4**: deterministic Playwright
execution, evidence-backed verification, correlated local artifacts, and basic
1080p video composition for manually authored DemoSpecs. It produces a verified
timeline and H.264 MP4 without relying on an LLM success claim. See
[the current stage](docs/CURRENT_STAGE.md) for the exact scope.

## Prerequisites

- Python 3.11 or newer
- Node.js 20.19 or newer
- npm 10 or newer
- FFmpeg and FFprobe with H.264 encoding support

## Backend setup

Create an isolated Python environment and install the project with development
tools:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m playwright install chromium
cp .env.example .env
```

Start the API:

```bash
proofdemo-api
```

The API runs at `http://127.0.0.1:8000`. Verify it with:

```bash
curl http://127.0.0.1:8000/health
```

Interactive API documentation is available at `http://127.0.0.1:8000/docs` in
development. It is disabled when `PROOFDEMO_ENVIRONMENT=production`.

## Frontend setup

In a second terminal:

```bash
npm --prefix frontend install
cp frontend/.env.example frontend/.env.local
npm --prefix frontend run dev
```

Open `http://127.0.0.1:5173`. The frontend checks the API health endpoint. Set
`VITE_API_BASE_URL` in `frontend/.env.local` to override its default API URL.

## Run the deterministic example

Start the separate Todo fixture in one terminal:

```bash
python scripts/serve_todo_app.py
```

Then execute the checked-in DemoSpec in another terminal:

```bash
proofdemo run examples/demo_spec.json --artifacts artifacts/todo-demo
```

A successful Stage 4 run exits `0`, transitions through `EXECUTED` to `PASSED`,
and writes `execution_report.json`, `trace.jsonl`, `browser.log.jsonl`,
`browser.webm`, `timeline.json`, `demo.mp4`, `artifact_manifest.json`, the
requested screenshot, and correlated evidence screenshots. The final MP4 is
H.264/yuv420p at 1920×1080 and 30 fps. `EXECUTED` continues to mean only that
browser actions completed; only the deterministic verifier can produce
`PASSED`, and only a verified integrity-checked run is composed.

The CLI uses exit code `1` for an action-level `FAILED` result, `2` for blocked
browser infrastructure or artifact output, and `64` for an invalid input spec.

## Validation

With the Python environment active and frontend dependencies installed, run:

```bash
python -m pytest
ruff format --check .
ruff check .
mypy backend/src
npm --prefix frontend run build
```

Export the shared DemoSpec schema after changing domain models:

```bash
python scripts/export_schema.py
```

The tests fail if
`shared/schemas/demo_spec.schema.json` does not match the authoritative Pydantic
model.

## Domain boundaries

- DemoSpec `1.2` uses stable Scene, Action, and Assertion IDs and requires at
  least one assertion per scene.
- `source_url` defines the allowed origin; every `goto` remains on that origin.
- `pause` is a presentation delay, not a page-readiness check.
- Literal fill values are non-sensitive demonstration data only.
- The browser adapter enforces the DemoSpec source origin before navigation and
  after redirects.
- Deterministic assertions cover element visibility, text containment, exact
  normalized URLs, completed downloads, and one declared JSON application
  state key.
- `EXECUTED` means actions completed. It does not mean assertions passed.
- `PASSED` requires every scene assertion to pass with structured evidence.
- Capture failures become explicit artifact warnings and trace events; they do
  not rewrite deterministic assertion outcomes.
- The artifact manifest records relative paths, media types, byte counts,
  SHA-256 digests, and stable correlation IDs for every other run artifact.
- Timeline policy is project-owned; FFmpeg is a narrow adapter for probing,
  scaling, letterboxing, and encoding.

## Repository map

```text
backend/src/proofdemo/  API, execution/verification/capture/render, and adapters
frontend/               React and TypeScript frontend
shared/schemas/         generated cross-runtime contracts
examples/               valid inputs and the deterministic Todo fixture
scripts/                deterministic developer utilities
tests/                  API and domain tests
docs/                   product, architecture, roadmap, and stage scope
```

## Project documents

- [Product specification](docs/PROJECT_SPEC.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Roadmap](docs/ROADMAP.md)
- [Current stage](docs/CURRENT_STAGE.md)

## Security

Never commit credentials or place them in DemoSpec files. `.env` is ignored;
`.env.example` documents non-secret configuration only. Stage 4 accepts only
non-sensitive literal fill data, constrains navigation to one origin, and does
not inject browser credentials. The application-state assertion reads one
validated top-level key and cannot execute spec-provided JavaScript. Fill
values are omitted from action trace payloads, and browser diagnostic text is
bounded and sanitized before persistence. Destructive-action safeguards remain
a later-stage requirement.
