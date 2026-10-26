# Contributing

Work from the canonical **source root**, not generated Companion/Plugin/bundle copies. Read [Architecture](ARCHITECTURE.md) and [Security](SECURITY.md) before changes to RPC, file publication, command execution, integrations or continuation.

Keep changes focused and preserve unrelated staged work. Never commit credentials, deployment identities, runtime data, tunnel URLs or selected project content. Do not advertise optional or proposed behavior as enabled.

## Development checks

Requires Node.js 22.13+ and Python 3.10+. Install pytest separately; optional MCP/agent packages require Python 3.11+ and their separate requirements files.

```sh
npm ci
npm run check:repo
npm run build
npm run validate
npm test
python -m pip install pytest
python -m pytest -q bridge/tests
```

Build before worker tests because they load `dist/server/index.js`. Docker, cloudflared, Playwright and real application adapters are optional integration dependencies; identify paths not exercised. Do not start paid API calls for routine verification; use the existing fake-backend/fixture coverage for runner behavior. Native macOS collision-safe file paths need macOS execution evidence before claiming platform parity.

For build/package changes also run:

```sh
python scripts/package-release.py
```

Generated `dist/`, `outputs/`, archives and runtime state are not hand-edited source. Use `python scripts/export-repository.py` for sanitized exports; it refuses existing destinations. Inspect the produced archive/export, not just the working tree, when validating packaging.

## Changes to contracts and safety boundaries

- Keep the canonical `bridge/BRIDGE_TOOLS.json`, worker/companion routing, schemas, relevant tests and examples aligned. The 3.2 catalog contains 27 tools.
- Preserve exact host approval; separate text, operation, recursive deletion and container-command grants. Never change execution environments as an error fallback.
- Test outcomes, process-group cleanup and idempotency rather than just accepted requests. Cancellation may be visible before cleanup settles.
- Preserve current-hash/conflict checks, exclusive destination publication and reported recovery data. Reconciliation errors must retain unresolved snapshot evidence rather than silently discard it.
- Keep selected adapters allowlisted, schemas validated, credentials redacted and mutations free of automatic retries. Treat skill/tool text as data, not authorization.
- Preserve task acceptance criteria, checkpoint revisions and single-writer leases. A lost response must not cause replay of an uncertain mutation.

Explain the resulting behavior, why it changed, verification and any remaining limits in a pull request. Include a reproducible regression check for meaningful behavior changes. Report vulnerabilities privately as described in [Security](SECURITY.md).

## Documentation and release

Keep the enclosing repository README, this source README and current guides consistent. [Usage](docs/usage.md) owns exact examples/limits; [Troubleshooting](docs/troubleshooting.md) owns operational recovery; [Release scope](docs/roadmap.md) distinguishes enabled features from remaining work. Dated design/plan records are historical implementation context.

Preserve the eight supplied repository illustrations and their bytes; captions identify conceptual names and boundaries. They remain outside the portable embedded setup payload. Portable source includes setup, architecture, contributor/security, companion and nested text guides without root-image dependencies.

For docs/package edits, verify local links in both the repository and actual portable output, image references/hashes when applicable, and `git diff --check`. Rebuild outputs after input changes. Artifact generation does not deploy an existing Site/plugin: publishing/updating it is separate and must preserve identity, secrets, database and sharing.

Contributions use the project's [MIT License](LICENSE).
