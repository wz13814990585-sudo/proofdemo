# Current Stage — Stage 3: Trace, Evidence Artifacts, and Browser Recording

## Goal

Persist what the deterministic executor and verifier actually did and observed.
Produce a correlated immutable trace, automatic evidence screenshots, sanitized
browser logs, browser video, and a hashed artifact manifest without changing
Stage 2 verification semantics.

## Required Outcomes

1. A versioned `TraceEvent` model records a monotonic sequence, UTC timestamp,
   event kind, stable scene/action/assertion correlation IDs, outcome, and
   JSON-compatible non-sensitive data.
2. The trace covers run transitions, action start/outcome, assertion outcome,
   scene outcome, artifact capture outcome, and browser-session closure.
3. Assertions with an available observation automatically receive a correlated
   evidence screenshot after scene verification. Stage 1 explicitly requested
   screenshots remain distinct execution artifacts.
4. The Playwright adapter records the browser session to WebM and returns the
   finalized recording path only after the browser context closes.
5. Browser console and page-error entries are captured in order, bounded, and
   sanitized before persistence.
6. A focused artifact writer atomically persists `execution_report.json`,
   `trace.jsonl`, `browser.log.jsonl`, and `artifact_manifest.json`.
7. The manifest records every other persisted artifact's relative path, kind,
   byte count, SHA-256 digest, and optional scene/assertion correlation. It
   cannot self-hash or reference paths outside the requested artifact directory.
8. `ExecutionReport` advances to version `3.0` and references trace, log,
   manifest, evidence screenshot, requested screenshot, and video paths.
9. Artifact capture failure is reported as an explicit warning and trace event;
   it cannot fabricate or reverse assertion evidence or a verification result.
10. Existing execution, verification, configuration, API, schema, lint, type,
    and frontend checks continue to pass.

## Acceptance Criteria

For the local Todo fixture, `proofdemo run` must still exit `0` and finish as
`PASSED`, while additionally producing:

- `execution_report.json`;
- `trace.jsonl` with contiguous sequence numbers and correlated action,
  assertion, scene, and run events;
- `browser.log.jsonl`;
- one requested screenshot and five correlated evidence screenshots;
- `browser.webm` with non-zero size;
- `artifact_manifest.json` whose sizes and SHA-256 digests match every listed
  file.

Automated tests must additionally prove that:

- fill values are absent from action trace payloads and browser logs are
  sanitized (the same non-sensitive text may legitimately appear as assertion
  evidence);
- evidence screenshot names cannot escape the artifact directory;
- trace order remains valid on `PASSED`, `FAILED`, and `BLOCKED` paths;
- a missing optional capture produces a warning without changing deterministic
  assertion results;
- manifest verification detects changed artifact bytes;
- browser resources and video finalize on success and failure.

The full validation suite remains:

```text
python -m pytest
ruff format --check .
ruff check .
mypy backend/src
npm --prefix frontend run build
```

## Not Included

- timeline editing, deterministic video composition, MP4 output, transitions,
  captions, or overlays;
- model planning, autonomous exploration, locator repair, or retries;
- credentials, cross-origin workflows, destructive actions, or production
  authentication;
- narration, TTS, DemoRecipe persistence, queues, workers, or cloud storage.

## Completion Status

`COMPLETE`
