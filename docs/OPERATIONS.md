# ProofDemo V1 Operations

## Supported deployment shape

V1 is a local modular monolith: CLI for demo workflows, optional FastAPI health
surface, Playwright Chromium, and local FFmpeg. It has no database, queue,
background worker, user authentication, cloud artifact store, or hosted
multi-tenant control plane. Add those only after measured workload requires them.

## Production configuration

Use an isolated Python environment and pinned lock/constraints in the deployment
system. Set:

```text
PROOFDEMO_ENVIRONMENT=production
PROOFDEMO_API_HOST=127.0.0.1
PROOFDEMO_API_PORT=8000
PROOFDEMO_FRONTEND_ORIGIN=https://your-frontend.example
```

Terminate TLS at a maintained reverse proxy. Production rejects non-HTTPS or
wildcard frontend origins, disables API docs, and sends HSTS/CSP plus defensive
response headers. Provider keys remain process environment secrets; never put
them in `.env` in a deployed environment, command history, specs, or artifacts.

## Release procedure

1. Run `proofdemo benchmark --output artifacts/benchmark_report.json`.
2. Run pytest, Ruff format/lint, mypy, schema export drift check, and frontend
   production build.
3. Run `python -m pip_audit --skip-editable` and
   `npm --prefix frontend audit --omit=dev`.
4. Run the real Todo `run` then `replay` acceptance and verify both manifests.
5. Review the diff for secrets and generated artifacts.
6. Merge a reviewable PR; tag only the validated merge commit.

CI performs the same automated gates with Chromium and FFmpeg.

## Artifact handling and retention

Artifact directories may contain application screenshots, logs, downloads, and
video. Store them on access-controlled encrypted storage. V1 has no automatic
retention or deletion service: operators must define a retention period, remove
expired directories with an approved recoverable process, and rotate any secret
suspected of appearing in a recording. Keep the source recipe and manifest with
retained videos so provenance remains inspectable.

Back up only artifacts that policy requires. Test restoration by running
`ArtifactWriter.verify` through application code or a replay preflight against a
copy. A valid hash is not a substitute for access control.

## Incident response

Stop active runs, preserve relevant manifests/logs, isolate affected artifacts,
and revoke possibly exposed provider or application credentials. Determine
whether leakage occurred in browser content, diagnostics, downloads, or video.
Report security issues privately as described in `SECURITY.md`. Resume only
after remediation and full release-gate validation.

## Capacity and failure semantics

Run directories are local and one CLI invocation is one foreground workflow.
Scale by isolated processes only after measuring CPU, disk, browser memory, and
FFmpeg time. Do not share an artifact directory between concurrent runs.
`FAILED` means a deterministic requested outcome failed; `BLOCKED` means an
external/runtime precondition prevented meaningful completion. Never retry by
rewriting either result.
