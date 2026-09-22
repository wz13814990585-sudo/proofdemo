# ProofDemo Security Policy

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability or exposed secret.
Use GitHub's private **Report a vulnerability** flow for this repository. Include
the affected commit, reproduction steps, impact, and whether any credential or
recording may have been exposed. Do not include live credentials in the report.

## Supported version

V1 (`1.x`) on `main` is the supported line. Security fixes are made on a branch,
validated with the complete release gates, and merged through a pull request.

## Security invariants

- DemoSpec, DemoRecipe, prompts, traces, logs, narration, and artifacts must not
  contain credentials.
- Navigation remains on the validated source origin.
- Credential-like fills are blocked. Named destructive, financial, account, and
  production actions require fresh explicit approval on every execution.
- A provider can propose only structured planning or repair output; it cannot
  control the browser, verifier, artifact integrity, or run status.
- A successful claim requires deterministic assertion evidence.
- Artifact paths stay inside their run directory and manifests bind bytes with
  SHA-256.

See [the threat model](docs/THREAT_MODEL.md) and
[operations guide](docs/OPERATIONS.md) for controls and residual risks.
