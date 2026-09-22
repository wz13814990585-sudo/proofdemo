# ProofDemo V1 Threat Model

## Assets and trust boundaries

Protected assets are user application data, credentials, DemoSpecs/recipes,
browser recordings, assertion evidence, provider keys, and final videos. Trust
boundaries exist at natural-language/provider calls, DemoSpec/recipe files, the
target web origin, Playwright, FFmpeg, artifact directories, and the local API.

Provider output is untrusted proposal data. DemoSpecs, repair candidates,
recipes, manifests, persisted reports, and media metadata are revalidated before
use. LLM text is never proof of execution or verification.

## Primary threats and controls

| Threat | V1 control |
| --- | --- |
| Cross-origin navigation or credential URL | strict HTTP origin validation in domain and browser adapter |
| Secret capture in fill traces/logs | credential-free contract, pre-execution fill policy, omitted fill payloads, diagnostic redaction |
| Destructive or financial click | semantic marker detection and fresh `--allow-risky-actions` approval per run/replay/repair |
| Provider prompt/output abuse | strict structured models, no tools, no persistence, explicit models, deterministic revalidation |
| False success claim | independent assertions, evidence, terminal `PASSED` gate, grounded narration |
| Path traversal or artifact replacement | contained resolved paths, atomic writes, byte count and SHA-256 manifest checks |
| Recipe/baseline tampering | semantic spec fingerprint, schema/profile preflight, provenance hashes |
| Media command injection | shell-free argument arrays, bounded timeouts, fixed codecs/filters |
| Resource exhaustion | bounded model fields, scene/action/assertion counts, pause budget, process timeouts, CI timeout |
| Browser diagnostic leakage | bounded redaction before persistence; provider keys stay in environment |

## Residual risks

V1 runs locally and does not supply authentication, a credential vault, tenant
isolation, sandboxed untrusted websites, malware scanning, or a retention
service. Semantic click screening cannot prove the effect of opaque or misleading
application labels. CSS and application behavior still require human DemoSpec
review. SHA-256 proves local byte consistency, not trusted authorship. External
application state can change between baseline and replay. OpenAI and target-site
availability remain external dependencies for opted-in features.

Run only against applications and data the operator is authorized to access.
Use a dedicated OS account/container and non-production fixture data for
untrusted targets.
