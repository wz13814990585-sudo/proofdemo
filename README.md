# ProofDemo

ProofDemo is a verified product demo system. Its long-term goal is to turn a web
application URL and natural-language intent into a polished, replayable demo
whose important claims are backed by observable evidence.

The product flow is:

```text
Intent -> Plan -> Execute -> Verify -> Capture -> Render
```

This repository currently implements **Stage 0 only**: project contracts,
DemoSpec validation, DemoRun lifecycle rules, an API health surface, a frontend
shell, and local developer tooling. See [the current stage](docs/CURRENT_STAGE.md)
for the exact scope.

## Prerequisites

- Python 3.11 or newer
- Node.js 20.19 or newer
- npm 10 or newer

## Backend setup

Create an isolated Python environment and install the project with development
tools:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
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
npm --prefix frontend run dev
```

Open `http://127.0.0.1:5173`. The frontend checks the API health endpoint. Set
`VITE_API_BASE_URL` in `frontend/.env.local` to override its default API URL.

## Validation

With the Python environment active and frontend dependencies installed, run:

```bash
python -m pytest
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

## Repository map

```text
backend/src/proofdemo/  API, configuration, and domain models
frontend/               React and TypeScript frontend
shared/schemas/         generated cross-runtime contracts
examples/               valid example product inputs
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
`.env.example` documents non-secret configuration only. Browser credentials,
recording redaction, and destructive-action safeguards must be designed before
browser automation is introduced.
