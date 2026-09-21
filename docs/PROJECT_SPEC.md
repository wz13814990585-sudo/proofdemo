# ProofDemo Product Specification

## Vision

Turn a product URL and natural-language demo intent into a verified,
replayable, polished product demo.

ProofDemo's defining property is verification. It must not present polished
footage that claims a capability succeeded when the real workflow could not be
verified.

## Users and Inputs

The initial user is a product, growth, sales, or developer team member who can
provide:

- a web application URL;
- a natural-language demo goal;
- optional audience and language;
- an optional approximate duration.

Credentials and other sensitive values are runtime inputs. They are never part
of DemoSpec, source control, logs, narration, or rendered artifacts.

## Outputs

A completed run should eventually produce:

- a versioned `DemoSpec`;
- a browser execution trace;
- deterministic assertion results and evidence;
- screenshots and browser recording;
- narration and presentation metadata;
- a polished 1080p MP4;
- a replayable `demo_recipe.json`;
- an artifact manifest tying claims to evidence.

## Core Flow

1. **Intent** — capture the requested product story.
2. **Explore** — inspect supported application surfaces safely.
3. **Plan** — produce a structured, reviewable DemoSpec.
4. **Execute** — perform specified actions in a real browser.
5. **Verify** — determine `PASSED`, `FAILED`, or `BLOCKED` from evidence.
6. **Capture** — persist events, screenshots, logs, and recordings.
7. **Narrate** — create text and audio aligned with verified scenes.
8. **Render** — compose verified material into the final video.
9. **Replay** — retain a recipe that can be re-run and diagnosed.

## Core Domain Concepts

- **DemoSpec** — versioned, declarative description of a demo and its scenes.
- **Scene** — a coherent product story beat containing ordered actions and
  expected outcomes.
- **Action** — one deterministic instruction such as navigation or input.
- **Assertion** — a deterministic expected outcome and its evidence policy.
- **DemoRun** — one lifecycle-tracked execution of a DemoSpec.
- **TraceEvent** — immutable observation from planning, execution, or capture.
- **Artifact** — a file or record produced by a run.
- **DemoRecipe** — replayable inputs plus stable execution metadata.

## Product Requirements

- Specs and persisted artifacts are versioned.
- Execution is deterministic wherever the application permits it.
- Verification is independent from narration and visual polish.
- A failed or blocked scene is never silently converted into success footage.
- Each important claim can be traced to its assertion and evidence.
- Local development remains supported throughout early stages.
- Model providers and media renderers sit behind narrow boundaries.

## Non-goals

ProofDemo is not:

- a general-purpose coding agent;
- a general video editor;
- arbitrary desktop automation;
- an autonomous purchasing system;
- a distributed enterprise workflow engine;
- a multi-agent swarm;
- an HTTP-native agent harness;
- an extension of MiniCodex.

## V1 Success Condition

A user can give ProofDemo a supported web application URL and a short request,
then receive a verified, replayable 1080p demo video. Every important success
claim is backed by recorded evidence, and failed or blocked scenes are reported
honestly.
