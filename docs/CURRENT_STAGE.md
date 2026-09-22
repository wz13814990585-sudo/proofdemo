# Current Stage — Stage 5: Bounded Demo Planner

## Goal

Turn a URL and natural-language demo intent into a reviewable DemoSpec `1.2`
candidate through one bounded structured-output model call. The planner may
propose; deterministic domain validation and the existing executor/verifier
remain authoritative.

## Required Outcomes

1. A strict `DemoIntent` model captures source URL, goal, audience, language,
   and optional target duration without credentials or executable content.
2. `PlanningService` depends on a narrow `PlannerPort`, never on a provider SDK.
3. The OpenAI adapter uses the Responses API structured-output parser with the
   authoritative Pydantic DemoSpec model, no tools, no browsing, no conversation
   persistence, and an explicit configured model name.
4. Provider output is revalidated by ProofDemo and rejected if its source URL
   differs from the requested origin, even when its JSON shape is valid.
5. Planning errors distinguish unavailable configuration/provider, model
   refusal/incomplete output, and invalid candidate contracts without exposing
   API keys or raw provider payloads.
6. `proofdemo plan URL --goal ... --output ...` atomically writes a candidate
   JSON spec for human review. It does not execute the candidate automatically.
7. The standard manually authored `proofdemo run` path remains fully usable
   without an API key or planner model.
8. The model name comes from `--model` or `PROOFDEMO_OPENAI_MODEL`; ProofDemo
   does not silently substitute a current/latest model.
9. Unit/contract tests use a fake planner. A provider-adapter test uses a fake
   SDK client and makes no network request.
10. Existing deterministic execution, verification, capture, rendering, lint,
    type, and frontend checks continue to pass.

## Acceptance Criteria

A fake provider planning the Todo goal must produce a valid DemoSpec `1.2` that
round-trips through JSON, preserves the requested origin, contains stable IDs,
starts with `goto`, and has at least one assertion per scene. Tests must also
prove rejection of cross-origin candidates, provider refusal, missing model
configuration, embedded URL credentials, and accidental automatic execution.

Live OpenAI planning is optional in local validation because it requires the
user's `OPENAI_API_KEY`, account access, and explicitly selected model. The
checked-in suite must never make a billable network request.

## Not Included

- autonomous exploration, screenshots as model input, DOM inspection, tool
  calls, locator repair, or retries;
- automatic execution of a newly planned candidate without review;
- narration, TTS, audio, recipe persistence, change detection, queues, or
  production provider routing.

## Completion Status

`COMPLETE`
