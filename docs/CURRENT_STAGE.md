# Current Stage — Stage 10: Benchmarks and Production Hardening

## Goal

Measure the core evidence pipeline against representative deterministic cases,
close the remaining safety and operational gaps, and declare V1 complete only
when measurable release gates and end-to-end acceptance pass.

## Required Outcomes

1. A versioned benchmark suite exercises verified success, assertion failure,
   action failure, and blocked infrastructure through the real application
   services with deterministic adapters.
2. The benchmark report measures terminal-outcome accuracy, evidence coverage,
   trace sequence/correlation integrity, per-case results, and explicit release
   thresholds. The checked-in suite must meet every threshold.
3. `proofdemo benchmark --output ...` runs offline, atomically writes its report,
   returns nonzero when a threshold fails, and makes no provider/network calls.
4. A deterministic pre-execution safety assessment blocks credential-like fills
   and requires fresh explicit approval for named destructive/financial/account
   actions. Replay and repair do not inherit prior approval.
5. Safety decisions and explicit approvals are persisted and integrity-recorded
   for every executed run without changing verification semantics.
6. DemoSpec collection and execution budgets prevent unbounded scene/action/
   assertion/pause workloads while preserving representative demos.
7. Production configuration rejects wildcard/insecure frontend origins, API
   responses use defensive headers, docs remain disabled in production, and
   diagnostics continue to redact common credential shapes.
8. CI runs schema drift, full tests (including Chromium/FFmpeg integration),
   Ruff, mypy, and frontend production build on supported versions.
9. Security policy, threat model, local-production operations, incident/retention
   guidance, release checklist, and deferred infrastructure decisions are
   documented truthfully.
10. The frontend and package metadata reflect V1 rather than a stale early-stage
    label; package/API version becomes `1.0.0`.
11. A final real Todo run and recipe replay produce verified manifests, 1080p
    H.264 video, compatible replay, and `UNCHANGED` comparison.
12. No database, queue, Kubernetes, cloud store, or background worker is added
    without benchmark evidence that the modular local runtime needs it.

## Release Gates

- terminal-outcome accuracy: `1.00`;
- expected evidence coverage: `1.00`;
- trace sequence/correlation integrity: `1.00`;
- full test suite, Ruff format/lint, mypy, schema drift, and frontend build pass;
- real Chromium/FFmpeg run-to-replay acceptance passes with valid hashes;
- repository contains no committed secret or generated runtime artifact.

## Not Included

- hosted multi-tenant control plane, user accounts, billing, cloud deployment,
  distributed queues/workers, Kubernetes, or remote artifact storage;
- scheduled monitoring, browser credential vault, arbitrary destructive-action
  execution, general DOM exploration, or autonomous repair loops;
- claims of scale, availability, or provider quality not measured here.

## Completion Status

`COMPLETE`

## V1 Acceptance Record — 2026-09-22

- Offline benchmark: `PASSED`; 4/4 representative cases passed with terminal
  outcome accuracy `1.0`, expected evidence coverage `1.0`, and trace
  integrity `1.0`.
- Automated validation: 133 tests passed under Python 3.12/pytest 9.1.1,
  including real Chromium and FFmpeg integration; Ruff format/lint, mypy over
  43 source files, generated-schema parity, and the frontend production build
  passed.
- Dependency review: `pip-audit --skip-editable` and
  `npm audit --omit=dev` reported no known vulnerabilities after raising the
  pytest and pip release floors used by development/CI.
- Real acceptance: the checked-in Todo DemoSpec produced a `PASSED` source run
  and a `PASSED` recipe replay. Both manifests verified with no integrity
  issues; replay preflight was `COMPATIBLE`; comparison was `UNCHANGED`.
- Media acceptance: both source and replay videos probed as H.264/yuv420p,
  1920x1080, 30 fps.
- Repository hygiene: tracked-file and credential-pattern scans found no
  generated runtime artifacts or common secret shapes.
