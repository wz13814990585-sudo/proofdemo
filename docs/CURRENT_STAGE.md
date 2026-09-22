# Current Stage — Stage 6: Grounded Narration and TTS

## Goal

Create an AI-voiced demo only from integrity-checked, verified scene evidence.
Narration text remains deterministically grounded in passed assertions; a speech
provider may synthesize that approved text but cannot create product claims.

## Required Outcomes

1. Narration accepts only a `PASSED` execution bundle, a valid artifact
   manifest, and the exact Stage 4 timeline and silent video recorded there.
2. Every narration cue maps to one verified timeline scene and cites at least
   one `PASSED` assertion ID from that scene.
3. Spoken success claims are deterministic templates derived from assertion
   evidence. No model is allowed to invent, rewrite, or expand product claims.
4. The first cue contains a concise disclosure that the voice is AI-generated,
   and `narration.json` records the disclosure and provider provenance.
5. `SpeechPort` and `AudioMixPort` isolate synthesis and media mechanics from
   evidence policy. Provider and FFmpeg SDK/process details stay in adapters.
6. The OpenAI speech adapter requires explicit model and voice configuration,
   requests WAV, atomically publishes output, and hides raw provider errors.
7. Per-scene WAV files are probed before mixing. Speech may be accelerated only
   within a bounded intelligibility limit; audio that cannot fit its verified
   scene is rejected instead of truncated or moved to another scene.
8. FFmpeg aligns cues to their scene ranges and produces `demo-narrated.mp4`
   with the unchanged H.264 video stream and an AAC audio stream.
9. `narration.json`, per-scene WAV files, and the narrated MP4 are integrity
   recorded in the artifact manifest with scene/assertion correlation.
10. `proofdemo run` remains fully usable without API credentials. Narration is
    opt-in through explicit TTS model and voice settings.
11. Tests use fake speech clients/ports and make no billable network requests;
    a real local FFmpeg test verifies timing and audio/video stream properties.
12. Existing planning, execution, verification, capture, render, lint, type,
    and frontend checks continue to pass.

## Acceptance Criteria

For a verified fixture with sufficient scene duration, narration must produce a
versioned evidence-linked script, one valid WAV per scene, and a 1920×1080,
30-fps H.264/AAC MP4 whose duration remains within one frame of the silent
video. A cue must begin inside its correlated scene and may not exceed that
scene after bounded tempo adjustment.

Tests must prove refusal of failed runs, tampered Stage 4 artifacts, missing or
mismatched timeline scenes, ungrounded evidence references, overlong speech,
missing provider configuration, provider failure, and accidental TTS use when
the user did not opt in.

Live speech generation is optional in local validation because it requires the
user's `OPENAI_API_KEY`, account access, and explicit model/voice choices. The
checked-in suite must never make a billable network request.

## Not Included

- model-written narration, captions, music, sound effects, transitions, zooms,
  or visual editorial changes;
- autonomous exploration, locator repair, scene repair, or reruns;
- DemoRecipe persistence, change detection, partial rerender, queues, workers,
  cloud media storage, or production provider routing.

## Completion Status

`COMPLETE`
