# ProofDemo

ProofDemo is a verified product demo system. Its long-term goal is to turn a web
application URL and natural-language intent into a polished, replayable demo
whose important claims are backed by observable evidence.

The product flow is:

```text
Intent -> Plan -> Execute -> Verify -> Capture -> Render
```

This repository currently implements **Stage 9**: a bounded optional planner,
deterministic execution and verification, correlated artifacts, 1080p video,
opt-in evidence-grounded narration, replay recipes, and deterministic UI change
detection plus review-required single-scene target repair. A model may propose a
reviewable DemoSpec or target repair, but it cannot execute either or claim
success; spoken product claims are fixed templates derived from passed
assertions. See
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

The deterministic pipeline does not require an API key. To use the optional
planner, set `OPENAI_API_KEY` in the environment and select an explicit model
with `PROOFDEMO_OPENAI_MODEL` or `--model`; ProofDemo never selects a floating
default model for you.

Opt-in narration additionally requires an explicit
`PROOFDEMO_OPENAI_TTS_MODEL` and `PROOFDEMO_OPENAI_TTS_VOICE` (or matching CLI
flags). The speech provider receives only already-approved narration text. The
[OpenAI text-to-speech guide](https://developers.openai.com/api/docs/guides/text-to-speech)
documents the WAV speech endpoint used by the adapter.

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

To create a candidate DemoSpec from a goal without running a browser:

```bash
proofdemo plan https://app.example.test/ \
  --goal "Create a launch task" \
  --model YOUR_EXPLICIT_MODEL \
  --output candidate.json
```

Review the generated file before passing it to `proofdemo run`. Planning is one
structured-output call with no tools or conversation persistence, and the
candidate is revalidated against the same-origin DemoSpec contract. See the
[OpenAI structured outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs)
for the provider mechanism used by the adapter.

For the checked-in deterministic example, start the separate Todo fixture in
one terminal:

```bash
python scripts/serve_todo_app.py
```

Then execute the checked-in DemoSpec in another terminal:

```bash
proofdemo run examples/demo_spec.json --artifacts artifacts/todo-demo
```

To add AI speech after the same run verifies successfully:

```bash
proofdemo run examples/demo_spec.json \
  --artifacts artifacts/todo-demo \
  --narrate \
  --tts-model YOUR_EXPLICIT_TTS_MODEL \
  --voice YOUR_EXPLICIT_VOICE
```

Narration is never implied by configured credentials; `--narrate` is required.
The first cue discloses that the voice is AI-generated.

Every successful run also writes `demo_recipe.json`. Replay it into a new
artifact directory with:

```bash
proofdemo replay artifacts/todo-demo/demo_recipe.json \
  --artifacts artifacts/todo-demo-replay
```

`replay_preflight.json` records the recipe/source provenance and every
compatibility issue before the browser starts. Replay narration remains opt-in
with the same `--narrate`, `--tts-model`, and `--voice` flags.

When the source `execution_report.json` is beside the recipe, replay also
verifies its recipe-recorded hash and writes `ui_change_report.json`. Use
`--baseline-artifacts PATH` to select a different baseline directory. An
explicit missing or invalid baseline stops before browser execution; a portable
recipe without local baseline evidence can still replay with change status
`NOT_EVALUATED`.

For a `CHANGED` replay, propose one bounded scene repair without executing it:

```bash
proofdemo propose-repair artifacts/todo-demo/demo_recipe.json \
  --change-artifacts artifacts/todo-demo-changed \
  --scene create_task \
  --hint "The submit button is now named Create task" \
  --model YOUR_EXPLICIT_MODEL \
  --output repair-candidate.json
```

After reviewing the candidate, explicitly approve execution:

```bash
proofdemo apply-repair artifacts/todo-demo/demo_recipe.json repair-candidate.json \
  --change-artifacts artifacts/todo-demo-changed \
  --baseline-artifacts artifacts/todo-demo \
  --artifacts artifacts/todo-demo-repaired
```

A fully verified repair writes `partial_render.json` and
`demo-repaired.mp4`. Unchanged scenes source their ranges from baseline video;
only the diagnosed scene sources new footage.

A successful Stage 4 run exits `0`, transitions through `EXECUTED` to `PASSED`,
and writes `execution_report.json`, `trace.jsonl`, `browser.log.jsonl`,
`browser.webm`, `timeline.json`, `demo.mp4`, `artifact_manifest.json`, the
requested screenshot, and correlated evidence screenshots. The final MP4 is
H.264/yuv420p at 1920×1080 and 30 fps. `EXECUTED` continues to mean only that
browser actions completed; only the deterministic verifier can produce
`PASSED`, and only a verified integrity-checked run is composed.

A successful run also writes `demo_recipe.json`, embedding the canonical
DemoSpec plus its fingerprint, fixed execution profile, schema requirements,
and hashes for the source execution report and final video.

An opted-in narrated run additionally writes `narration.json`, one PCM WAV per
scene, and `demo-narrated.mp4` with H.264 video and AAC audio. Every cue cites a
passed assertion and retains the exact verified scene bounds.

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
- A planner can propose only a DemoSpec candidate. ProofDemo revalidates it,
  preserves the requested origin, and requires a separate explicit run command.
- Narration uses only short project-owned phrases selected by passed assertion
  type. TTS synthesizes those phrases but cannot author or expand claims.
- Speech that cannot fit its scene within the bounded tempo policy is rejected;
  it is not truncated, shifted, or allowed to cover another scene.
- A recipe is portable input, not trusted execution authority. Replay validates
  its spec fingerprint, versions, schemas, and execution profile first, then
  delegates to the same deterministic pipeline and creates a fresh run ID.
- UI change detection compares stable action/assertion IDs and structured
  observations against the verified baseline. It reports change categories but
  cannot rewrite selectors, assertions, run status, or footage.
- Repairs may replace only diagnosed typed targets on existing click/fill
  actions or element/text assertions in one scene. Applying a reviewed proposal
  reruns the complete DemoSpec; partial rendering occurs only after `PASSED`.

## Repository map

```text
backend/src/proofdemo/  API, planning/execution/verification/media, and adapters
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

Never commit credentials or place them in DemoIntent or DemoSpec files. `.env` is ignored;
`.env.example` documents non-secret configuration only. Stage 4 accepts only
non-sensitive literal fill data, constrains navigation to one origin, and does
not inject browser credentials. The application-state assertion reads one
validated top-level key and cannot execute spec-provided JavaScript. Fill
values are omitted from action trace payloads, and browser diagnostic text is
bounded and sanitized before persistence. Stage 9 reads provider credentials
only from the environment and never stores them in planner inputs, candidates,
traces, narration text, or artifacts. TTS receives only non-sensitive grounded
phrases, and artifact metadata records the AI voice disclosure. Recipes contain
no environment snapshot, cookies, storage state, or credentials. Destructive-
action safeguards remain a later-stage requirement.
