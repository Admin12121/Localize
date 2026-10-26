# Web-Bridge

**A private ChatGPT Site gateway and locally controlled companion for project work.**

Version **3.2.0** · Windows, macOS and Linux · Created by **admin12121** · [MIT](LICENSE)

Inspect and change a selected project, request commands on the host or in Docker, use selected skill/MCP adapters, and save tasks with evidence for later continuation. The local owner chooses permissions, command profiles, integrations and approvals.

```text
ChatGPT → your private Site / MCP gateway → authenticated HTTPS
                                                ↓
                                  local Python companion
                                    ├─ selected project and saved tasks
                                    ├─ approved web targets / MCP adapters
                                    └─ host, snapshot or live Docker jobs

Separate loopback panel → project, grants, approvals, Docker setup, pause
```

The Site validates and forwards tool calls. It cannot grant local access. Tunnel only authenticated RPC, never the local control panel.

## Connect

1. Provision your own private Site using [SETUP](SETUP.md). Importing the setup plugin alone does not deploy a Site.
2. Install Python 3.10+ and [cloudflared](https://developers.cloudflare.com/tunnel/downloads/). Download the trusted `Web-Bridge.pyz`.
3. Run `python Web-Bridge.pyz` on Windows or `python3 Web-Bridge.pyz` on macOS/Linux. Core features need no pip installation or extraction.
4. Open the printed local panel, enter its control code, select a project, and save permissions and a command profile.
5. Store the printed remote endpoint/key only in your private Site's connection form. Select its generated plugin in ChatGPT and call `bridge_status`.
6. Verify a known file read and a harmless approved command in the chosen environment. Keep the companion running.

The bundle starts a Quick Tunnel by default; `--local-only` disables it. From this source root, use `python bridge/launch.py --tunnel`; the source launcher tunnels only when requested.

## Capabilities

| Area | Implemented in 3.2 |
| --- | --- |
| Workspace | Bounded list/search/read, hash-checked text edit/nested create, mkdir, move, recoverable delete/restore |
| Commands | Shell text or exact argv; explicit local profile; launch evidence, success/failure, timeout/cancel, incremental output |
| Docker | Filtered snapshot jobs or persistent live project; local engine/image/container setup and validated attachment |
| Integrations | Built-in project-work skill, selected skill folders, allowlisted stdio/HTTP MCP tools |
| Saved work | SQLite tasks, checkpoints/evidence/handoff, single-writer leases and file/command verification |
| Continuation | ChatGPT resume on the next prompt; optional explicitly started API-backed local runner |
| HTTP/browser | Approved-origin requests/forms/session evidence; optional scoped Chromium |

Host commands use your OS account and always require exact per-command approval. Live Docker shares the real project and can mutate it directly. Snapshot changes need applicable text/operation permissions; unsupported or unresolved changes retain a local artifact. Reading a skill does not install tools or grant application access.

Default command timeout is 600 seconds; the local maximum can be set up to 3,600 seconds. Output is bounded to 64,000 bytes; detailed history rolls at 200 jobs with session idempotency receipts. Text files are bounded to 256,000 bytes; snapshots to 50 MB/5,000 entries. See [Usage](docs/usage.md) for exact limits and all 27 tools.

Automatic ChatGPT event prompts are **not enabled** (`chatgpt_events: false`). Skills cannot extend platform limits. The optional local agent uses separately configured API credentials and step/time/token budgets; these are not a fixed-price guarantee. No API call is needed for core use or saving agent setup.

## Documentation

- [Documentation index](docs/index.md)
- [Setup and upgrading from 3.1](SETUP.md)
- [Usage and tool examples](docs/usage.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Architecture](ARCHITECTURE.md)
- [Companion reference](bridge/README.md)
- [Release scope and remaining work](docs/roadmap.md)
- [Contributing](CONTRIBUTING.md) and [Security](SECURITY.md)

This source package is self-contained text. Repository illustrations are intentionally excluded from the embedded setup payload.

## Develop

Run from this source root. Requires Node.js 22.13+ and Python 3.10+; optional MCP and local-agent dependencies require Python 3.11+.

```sh
npm ci
npm run check:repo
npm run build
npm run validate
npm test
python -m pip install pytest
python -m pytest -q bridge/tests
python scripts/package-release.py
```

```text
bridge/          Python companion, local controls, jobs, integrations and tasks
worker/          Private Site interface and MCP gateway
db/, drizzle/    Encrypted connection schema and migrations
setup-plugin/    Private-Site provisioning workflow
scripts/         Build, packaging, validation and sanitized source export
tests/           Worker tests; Python tests live in bridge/tests/
docs/            User guides and dated design/implementation records
```

Generated artifacts go to `dist/` and `outputs/`; rebuild rather than editing distribution copies. `python scripts/export-repository.py` exports sanitized source and refuses an existing destination. Updating local packages does not publish an installed Site/plugin.

Keep credentials, runtime directories, tunnel logs and selected project data out of Git/releases. Work only on authorized projects and targets. This project has not been independently security audited.
