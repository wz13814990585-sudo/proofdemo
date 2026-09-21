# ProofDemo Repository Instructions

## Mission

ProofDemo turns a web application URL and a natural-language demo goal into a
verified, replayable product demo. Its product flow is:

`Intent -> Plan -> Execute -> Verify -> Capture -> Render`

ProofDemo is not merely a screen recorder or AI video generator. A claim of
success must be backed by observable evidence; never treat an LLM statement as
proof. Important outcomes should use deterministic checks against DOM state,
navigation, network responses, downloads, application state, or artifacts.
Results must distinguish `PASSED`, `FAILED`, and `BLOCKED`.

## Read Before Substantial Work

Read these sources of truth before implementation:

- `docs/PROJECT_SPEC.md`
- `docs/ARCHITECTURE.md`
- `docs/ROADMAP.md`
- `docs/CURRENT_STAGE.md`

`docs/CURRENT_STAGE.md` defines the active scope. Do not implement later stages
unless the user explicitly changes the scope. Record useful future work in the
roadmap instead of silently adding it.

## Engineering Rules

- Prefer deterministic code for state transitions, validation, retries,
  persistence, recording, rendering, timing, and artifact handling.
- Reserve model reasoning for intent interpretation, ambiguous UI decisions,
  planning, and narration where it provides clear value.
- Keep the architecture modular and locally usable, but simple.
- Do not introduce agent hierarchies, distributed infrastructure, queues,
  microservices, or Kubernetes without a current-stage requirement.
- Do not integrate MiniCodex or create a separate HTTP-native agent framework.
- Inspect relevant code and make the smallest coherent change. Preserve working
  behavior and avoid parallel implementations.
- Use mature libraries for commodity functions. Keep DemoSpec, verification,
  execution semantics, replay logic, trace-to-video mapping, and evaluation
  under project control.
- Use typed interfaces, structured models, explicit errors, focused modules,
  and testable boundaries. Avoid hidden global state and stringly typed internal
  protocols.
- Never commit secrets or expose them in recordings, screenshots, logs, or
  artifacts. Use environment variables and `.env.example`.

## Completion Rules

A task is complete only when its current-stage acceptance criteria are checked.
Before completion:

1. run relevant tests and configured lint/type checks;
2. exercise the changed behavior where feasible;
3. inspect failures instead of bypassing them;
4. update documentation when architecture or behavior changed;
5. report only validation that was actually run.

Do not weaken a test or acceptance criterion merely to obtain a pass. Separate
implementation failures from environment failures, unrelated regressions,
flaky tests, and invalid test assumptions.

Completion reports should cover what changed, design decisions, files changed,
validation results, and intentionally deferred work.
