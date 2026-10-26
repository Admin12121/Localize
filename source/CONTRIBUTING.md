# Contributing

Web-Bridge accepts focused improvements to the local companion, private Site worker, build pipeline, tests, and documentation. Changes should preserve its permission boundaries and avoid claiming capabilities that have not been tested.

## Before changing code

- Work from the canonical **source root**, not an extracted `Companion/`, `Plugin/`, or `.pyz` release.
- Read [ARCHITECTURE.md](ARCHITECTURE.md) and [SECURITY.md](SECURITY.md) when changing any RPC, HTTP, file, or command execution behavior.
- Do not check in credentials, Site identities, local runtime directories, tunnel URLs, project files, or test fixtures containing private user data.
- Keep changes small enough to review; avoid unrelated formatting or directory churn.

## Development checks

Requires Node.js 22.13+ and Python 3.10+:

```sh
npm ci
npm run build
npm run validate
npm test
python -m pytest -q bridge/tests
```

Install pytest separately for Python tests. Docker, cloudflared, and Playwright are optional components for their relevant integration paths; state clearly when those checks were not run.

For build or release changes, additionally run:

```sh
python scripts/package-release.py
```

Keep `dist/`, `outputs/`, local runtime state, and generated archives out of source commits.

## Pull-request checklist

- Explain what changed, why, and which component owns the behavior.
- Include a reproducible test or a clear manual verification procedure.
- Confirm no change silently grants filesystem, host-execution, or network privileges.
- If a tool contract changes, update `bridge/BRIDGE_TOOLS.json`, routing, tests, and the relevant docs together.
- If build inputs change, update the portable-source packaging manifest so fresh installations include them.
- Identify remaining limitations and tests you could not run.

## Vulnerabilities

Do not post working exploits, live secrets, or identifying private logs in public issues. Follow the private reporting guidance in [SECURITY.md](SECURITY.md).

Contributions are provided under the project's [MIT License](LICENSE).

## Documentation and illustrations

Keep root and source READMEs aligned about supported features. Use `docs/usage.md` for exact API examples and `docs/troubleshooting.md` for known defects. Proposed features belong in `docs/roadmap.md` and the dated design, never in a table of implemented capabilities.

The enclosing repository stores the eight supplied illustrations under `docs/images/`, with captions in `docs/illustrations.md`. Preserve their bytes when renaming. Do not treat conceptual image labels as API names or silently advertise capabilities shown in an illustration.

Portable-source packaging must include `SETUP.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md`, `bridge/README.md` and all text guides under `docs/`. Repository illustrations stay outside the embedded setup payload. For documentation/packaging changes, verify relative links in the actual portable archive/export, image references/hashes in the enclosing repository, and `git diff --check`. Run build/validation and relevant existing tests when package inputs change. Keep installation instructions explicit about working directory and optional test dependencies.
