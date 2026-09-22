# Current Stage — Stage 4: Deterministic Video Composition

## Goal

Transform an integrity-checked, verified browser recording into a repeatable
timeline and a basic 1920×1080 MP4. Keep timeline semantics under project
control and delegate commodity media probing/encoding to an FFmpeg adapter.

## Required Outcomes

1. Composition accepts only a Stage 3 report whose run and verification status
   are both `PASSED` and whose artifact manifest passes integrity checks.
2. A versioned timeline maps every verified scene to deterministic millisecond
   boundaries derived from correlated trace events and source-video duration.
3. Timeline validation requires ordered, non-overlapping, positive scene ranges
   that cover the complete source recording.
4. An application-owned `RenderPort` separates timeline policy from FFmpeg
   process invocation and media probing.
5. The FFmpeg adapter produces 1920×1080, 30 fps, H.264/yuv420p MP4 with a
   fixed letterbox policy, no audio, stripped input metadata, and bounded
   execution errors.
6. Rendering the same verified source and timeline twice produces identical
   output bytes in the supported local environment.
7. `timeline.json` and `demo.mp4` are added to the Stage 3 artifact manifest
   with byte counts and SHA-256 digests.
8. `proofdemo run` composes automatically only after a verified `PASSED` run.
   Failed, blocked, or tampered runs never produce success video.
9. Missing FFmpeg is reported as a blocked render precondition without changing
   the underlying execution or verification evidence.
10. Existing execution, verification, capture, schema, lint, type, and frontend
    checks continue to pass.

## Acceptance Criteria

For the local Todo fixture, `proofdemo run` must exit `0` and additionally
produce:

- `timeline.json` with the verified `create_task` scene covering the source;
- `demo.mp4` with H.264 video at exactly 1920×1080 and 30 fps;
- a non-zero duration matching the browser recording within one output frame;
- final manifest records and valid hashes for the timeline and MP4;
- no video output when the example assertion is deliberately made false.

Automated tests must prove timeline invariants, refusal of unverified/tampered
inputs, deterministic repeated rendering, FFmpeg-unavailable behavior, and
real media properties through FFprobe.

The full validation suite remains:

```text
python -m pytest
ruff format --check .
ruff check .
mypy backend/src
npm --prefix frontend run build
```

## Not Included

- scene transitions, zooms, cursor effects, overlays, captions, music, or
  editorial trimming;
- narration, TTS, audio mixing, or lip/timing alignment;
- model planning, autonomous exploration, locator repair, or retries;
- DemoRecipe persistence, partial rerendering, queues, workers, or cloud
  rendering.

## Completion Status

`COMPLETE`
