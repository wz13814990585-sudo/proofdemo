# ProofDemo Release Checklist

Use this checklist for every V1 release candidate. Record commands and actual
results; do not infer a pass from an earlier stage or another machine.

## Automated gates

- [ ] `python scripts/export_schema.py` leaves the committed schema unchanged.
- [ ] `proofdemo benchmark --output ...` reports `PASSED` and all three metrics
  equal `1.0`.
- [ ] `python -m pytest` passes, including available Chromium/FFmpeg integration.
- [ ] `ruff format --check .` and `ruff check .` pass.
- [ ] `mypy backend/src` passes.
- [ ] `npm --prefix frontend run build` passes.
- [ ] `python -m pip_audit --skip-editable` and
  `npm --prefix frontend audit --omit=dev` report no known vulnerabilities.

## Real acceptance

- [ ] Start the checked-in Todo fixture and run `examples/demo_spec.json` with
  real Playwright Chromium and FFmpeg.
- [ ] Replay the generated recipe against its source artifacts.
- [ ] Both runs are `PASSED`; both manifests verify; the replay preflight is
  compatible; UI change status is `UNCHANGED`.
- [ ] Both final videos probe as H.264/yuv420p, 1920x1080, and 30 fps.

## Security and repository review

- [ ] Review the diff and dependency advisories.
- [ ] Confirm no secret, `.env`, browser state, or generated run artifact is
  tracked.
- [ ] Confirm `SECURITY.md`, the threat model, and operations guidance still
  describe the shipped behavior and residual risks.
- [ ] Merge a reviewable PR and tag only the validated merge commit.

The first V1 validation record is kept in `docs/CURRENT_STAGE.md`; subsequent
release records belong in the release PR or release notes.
