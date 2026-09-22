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

Through Stage 8, the application layer contains a bounded planning service plus
focused deterministic execution, verification, tracing, artifact-persistence,
composition, narration, recipe, replay-preflight, and change-detection services.
Browser, media, and provider mechanics sit behind application-owned ports
implemented by Playwright Chromium, FFmpeg, and optional OpenAI adapters.

## Technology Choices

- **Python 3.11+** for backend and core product logic.
- **FastAPI** for a typed, inspectable HTTP boundary.
- **Pydantic v2** as the authoritative runtime model and JSON Schema source for
  DemoSpec.
- **Pydantic Settings** for validated `.env` and process-environment loading.
- **React, TypeScript, and Vite** for a small, independently runnable frontend.
- **pytest** for backend/domain tests; **Ruff** and **mypy** for static checks.
- **Playwright** supplies the Chromium adapter behind an
  application-owned port.
- **FFmpeg/FFprobe** provide commodity media probing, scaling, letterboxing,
  and H.264 encoding behind a render port. ProofDemo owns timeline policy.
- **OpenAI Responses API** provides optional structured planning behind a
  planner port, with an explicit model, no tools, and no stored conversation.
- **OpenAI Speech API** optionally synthesizes approved cue text as WAV behind a
  speech port. It does not receive assertion payloads or author narration.

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
| Trace/artifact persistence | deterministic trace recorder and artifact writer |
| Video composition | deterministic render adapter |
| Intent-to-DemoSpec planning | model behind a narrow boundary |
| Ambiguous UI resolution | model-assisted, evidence recorded |
| Narration claim text | deterministic passed-assertion templates |
| Speech synthesis | provider behind a narrow boundary |
| Audio alignment | deterministic timeline policy and FFmpeg adapter |
| Recipe compatibility | deterministic application policy |
| Replay execution | existing execution/verification/media services |
| UI change diagnosis | deterministic stable-ID evidence comparison |

## DemoSpec Execution Contract

Schema version `1.2` uses stable IDs for every Scene, Action, and Assertion and
requires at least one assertion per scene.
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

## Execution and Verification Boundary

`ExecutionService` accepts an already validated DemoSpec, a `BrowserPort`, and
an artifact directory. It executes each scene's actions in declared order,
delegates that scene's assertions to `VerificationService`, and emits an
`ExecutionReport` with the
immutable DemoRun, ordered action results, scene/assertion results, requested
screenshot paths, and the aggregate verification status.

The browser port contains only `open`, `goto`, `click`, `fill`, `pause`,
`screenshot`, deterministic observation, and idempotent `close` operations.
The Playwright adapter owns locator translation, browser lifecycle, Playwright
error translation, download observation, the constrained application-state
read, and runtime same-origin enforcement. The application service owns
ordering, comparisons, evidence models, run/scene transitions, result
correlation, and contained screenshot paths.

Browser startup and runtime availability errors produce `BLOCKED`. A requested
action or observable expectation that deterministically fails produces
`FAILED`. Every assertion in every scene passing moves the run through
`EXECUTED` to `PASSED`. Browser resources are closed before the final `PASSED`
transition and on every failure path.

DemoSpec `1.2` supports `element_visible`, `text_contains`, `url_equals`,
`download_completed`, and `app_state_equals`. Evidence stores JSON-compatible
expected and observed values under the stable `scene_id/assertion_id` key. The
application-state assertion can read only a validated top-level key from an
opt-in `window.__PROOFDEMO_STATE__` object; the spec cannot provide executable
JavaScript.

The Todo fixture under `examples/todo_app/` is deliberately independent of the
ProofDemo frontend. It is a deterministic execution target, not product UI.

## Planner Boundary

`PlanningService` accepts a strict `DemoIntent` and a `PlannerPort`. The OpenAI
adapter makes one structured-output request whose parsed type is the
authoritative DemoSpec model. It has no browser, trace, execution, or artifact
capability and cannot enter the DemoRun lifecycle.

ProofDemo reconstructs the returned model through domain validation and rejects
any candidate whose normalized source origin differs from the requested origin.
The result is explicitly a review-required proposal: `proofdemo plan` writes it
atomically, while `proofdemo run` remains a separate user action. Missing model
or provider configuration blocks only planning; manually authored DemoSpecs
continue through the deterministic pipeline without model access.

## Trace and Artifact Boundary

`TraceRecorder` produces immutable versioned events with contiguous sequence
numbers, UTC timestamps, stable correlation IDs, outcomes, and JSON-compatible
data. Action trace payloads include action type and outcome but never the fill
value. Assertion trace payloads may contain the non-sensitive expected and
observed evidence already authorized by DemoSpec.

The Playwright adapter owns browser video finalization plus bounded, sanitized
console and page-error collection. It returns these only after closing the
browser context. `ExecutionService` coordinates automatic evidence screenshots
without changing verifier results when an optional capture fails.

`ArtifactWriter` atomically writes the report, trace, and browser log, then
hashes those files together with requested screenshots, evidence screenshots,
and browser video. `artifact_manifest.json` records SHA-256, byte count, media
type, and correlation metadata for every other artifact; a manifest cannot
cryptographically include itself. All artifact paths are resolved and checked
against the requested root before use.

## Timeline and Render Boundary

`CompositionService` accepts only an integrity-checked Stage 3 bundle whose run
and verification statuses are both `PASSED`. It maps stable scene IDs to
contiguous millisecond ranges by scaling correlated action/scene trace times to
the probed browser-video duration. The versioned timeline always covers the
complete source with positive, ordered, non-overlapping scene ranges.

The FFmpeg adapter receives only a source path, output path, and fixed render
settings. Stage 4 composition uses a 1920×1080 canvas, 30 fps, aspect-preserving
Lanczos scale, fixed letterbox color, H.264/yuv420p, no audio, stripped metadata,
and one encoding thread for repeatability. FFprobe validates dimensions, frame
rate, codec, and duration after render. `timeline.json` and `demo.mp4` are then
hashed into the final artifact manifest.

## Narration and Audio Boundary

`NarrationService` accepts only a verified `PASSED` bundle plus an
integrity-checked Stage 4 manifest and its exact persisted timeline. It selects
one passed assertion per scene by deterministic priority and maps its type to a
short project-owned phrase. `validate_narration_grounding` recomputes the
allowed phrase, assertion reference, scene identity, and timeline bounds; free
model-authored success text is not accepted.

`SpeechPort` receives only approved cue text. The OpenAI adapter requires an
explicit model and voice, requests PCM WAV, publishes files atomically, and
returns no authority over evidence or timing. The first cue includes a spoken
AI-voice disclosure.

Each WAV is probed before use. Speech can be accelerated by at most 2× to fit
its own verified scene; longer speech is rejected instead of truncated or moved.
`AudioMixPort` aligns cues, pads silence, and preserves the Stage 4 H.264 stream
while adding AAC audio. The narration track, correlated WAV files, and narrated
MP4 are included in the integrity manifest.

## DemoRun Lifecycle

Stage 7 preserves this legal state graph; planning, rendering, narration, and
replay preflight cannot change it:

```text
CREATED -> VALIDATED -> RUNNING -> EXECUTED -> PASSED
    |          |          |          |
    |          |          |          `-> FAILED / BLOCKED
    |          |          |------------> FAILED / BLOCKED
    |          |-----------------------> FAILED / BLOCKED
    `----------------------------------> FAILED / BLOCKED
```

`EXECUTED` means all requested browser actions completed; it is not a verified
success result. Only evidence-backed verification enables `EXECUTED -> PASSED`.

`PASSED`, `FAILED`, and `BLOCKED` are terminal. The state transition function
is pure: it constructs a fully revalidated model and appends an immutable
history entry. All timestamps are timezone-aware and normalized to UTC.

## Recipe and Replay Boundary

`DemoRecipe` embeds the canonical DemoSpec and its semantic SHA-256 fingerprint,
the fixed Chromium/headless/1280×720 execution profile, supported schema
requirements, generator version, and source provenance. Provenance cites the
verified execution report and preferred final video by manifest hash. It does
not include browser storage, credentials, environment values, provider keys, or
logs.

`RecipeService` creates a recipe only from a verified `PASSED` bundle and an
integrity-checked manifest with matching run/spec identities. Compatibility
checks collect every unsupported recipe/schema/engine/profile constraint and
fingerprint mismatch into `replay_preflight.json` before Playwright is created.

A compatible replay passes the embedded DemoSpec to the same CLI orchestration,
`ExecutionService`, verifier, artifact writer, and media services. The preflight
report is recorded in the new run's manifest; the replay receives a fresh run ID
and emits a new recipe. Speech remains a separate explicit opt-in.

## Change Detection Boundary

Before comparison, `ChangeDetectionService` resolves the source execution report
inside the selected baseline directory, verifies its SHA-256 against recipe
provenance, parses the strict report schema, and requires matching source run,
spec, and `PASSED` status. An explicit missing or invalid baseline stops before
browser construction.

After replay, the service compares baseline and current results by stable
`scene_id/action_id` and `scene_id/assertion_id`. It classifies missing or failed
actions, likely locator/selector failures, failed assertions, changed passing
observations, and broken scene assumptions. No visual heuristic or model is
used. `ui_change_report.json` is persisted even for a failed replay and never
changes verification or lifecycle status. A copied portable recipe with no
local baseline can replay with an explicit `NOT_EVALUATED` report.

## Configuration and Security

Configuration comes from `.env` and `PROOFDEMO_` environment variables, with
real environment variables taking precedence. It contains no secret defaults.
The documented frontend and API defaults both use `127.0.0.1`. The API exposes
only non-sensitive service metadata. Browser navigation is constrained to the
validated source origin, screenshots cannot escape their artifact directory,
and literal fills are restricted by contract to non-sensitive demo data. The
application-state hook accepts a validated key as data rather than code.
Diagnostic logs are bounded and sanitized, and fill values are not copied into
action trace payloads. Provider credentials are read only from environment
configuration and are never admitted to DemoIntent, DemoSpec, traces, or
artifacts. Speech receives only fixed, non-sensitive phrases. Recipes omit
environment snapshots, browser session state, and credentials. Stage 8 does not
support browser credential injection.

## Deliberate Deferrals

There are no model tools, model-written narration, autonomous exploration,
locator repair, editorial transitions, zooms, overlays, captions, music,
database, queue, model diagnosis, repair, partial rerender, or cloud artifact
store through Stage 8. Those are introduced only when their roadmap
stage supplies executable acceptance criteria.
