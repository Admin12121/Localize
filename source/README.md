# Web-Bridge

**A private ChatGPT Site gateway and locally controlled Python companion.**

Version **3.1.1** · Windows, macOS and Linux · Created by **admin12121** · [MIT](LICENSE)

Use ChatGPT to inspect a selected project, propose UTF-8 text changes, send requests to approved websites, and request commands in temporary Docker containers or on the host. The local owner selects the project and permissions, reviews operations, and can pause access.

## How it works

```text
ChatGPT → your private Site / MCP gateway → authenticated HTTPS
                                                ↓
                                  local Python companion
                                    ├─ approved web targets
                                    ├─ selected project files
                                    └─ approved command jobs

Separate loopback control panel → project, permissions, approvals, pause
```

The Site validates and forwards tool calls. Local policy decides whether they can run. The authenticated RPC endpoint can be tunneled; the control panel must stay local.

## Connect

1. Create your own private Site through the setup workflow in [SETUP.md](SETUP.md). Your account needs the relevant Sites/plugin/build capabilities; importing a plugin alone does not deploy a Site.
2. Install Python 3.10+ and [cloudflared](https://developers.cloudflare.com/tunnel/downloads/). Download `Web-Bridge.pyz` from your private Site or trusted release.
3. Run `python Web-Bridge.pyz` on Windows, or `python3 Web-Bridge.pyz` on macOS/Linux. No pip installation or extraction is needed for core companion features.
4. Open the printed local control panel, enter its local control code, select a project, and enable the capabilities you want.
5. Paste the printed Site endpoint and connection key only into your private Site's connection form. Keep the companion running.
6. Select your Site-generated plugin in ChatGPT, call `bridge_status`, then verify a read or approved command result.

The bundle starts a Quick Tunnel by default. `--local-only` disables that tunnel. A source checkout can run `python bridge/launch.py --tunnel` from this directory. Use `python3` on macOS/Linux.

## Capabilities and limits

| Area | Implemented in 3.1.1 |
| --- | --- |
| Workspace | List, literal search, UTF-8 read and proposed edits; new files in existing directories |
| Commands | Asynchronous submission, local approval, polling/output, cancellation; Docker snapshot or host |
| HTTP labs | Approved origins, requests, forms, cookies, bounded request history |
| Optional browser | Approved-origin Chromium actions with locally installed Playwright |
| Controls | Project/permission selection, approvals, pause and revocation |

Host commands use the OS account and can reach beyond the selected project. They require exact local approval every time. Docker commands use a filtered temporary copy and one of three pre-pulled Linux images. Networking and automatic text-change application are separate local options.

Current commands are limited to 120 seconds, 64 KB output, and 30 retained jobs per session. File tools handle up to 256 KB per text file. There is no folder-creation, rename, deletion, binary-edit, existing-container attachment, local MCP client, or autonomous continuation API yet. Docker snapshot deletions are not applied to the original project.

**Known issue:** `completed` can accompany a nonzero command exit. Check exit code, output and the requested effect. Approval alone is never proof of execution. See [troubleshooting](docs/troubleshooting.md).

## Documentation

- [Documentation index](docs/index.md)
- [Setup and upgrades](SETUP.md)
- [Usage, tool examples and limits](docs/usage.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Architecture and source ownership](ARCHITECTURE.md)
- [Companion reference](bridge/README.md)
- [Proposed upgrades and continuation modes](docs/roadmap.md)
- [Contributing and verification](CONTRIBUTING.md)
- [Security and reporting](SECURITY.md)

The enclosing development checkout also contains an illustrated repository README and a diagram gallery. This portable-source README is self-contained and does not depend on those large image assets.

## Develop

Run from this source root. Requires Node.js 22.13+ and Python 3.10+; pytest is a separate development dependency.

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
bridge/          Python companion, local controls, workspace and job services
worker/          Site interface and MCP gateway
db/, drizzle/    Connection schema and migrations
setup-plugin/    Private-Site provisioning workflow
scripts/         Build, packaging, validation and source export
tests/           Worker tests; bridge/tests/ contains Python tests
docs/            Usage, troubleshooting and proposed upgrade design
```

Generated artifacts go to `dist/` and `outputs/`. Export a clean source-first checkout with `python scripts/export-repository.py`; an existing destination is never overwritten. Publish `.pyz` and ZIP artifacts as release assets. Do not edit generated distribution copies independently.

Keep runtime credentials, connection records, tunnel logs, and selected project data out of Git. This software has not been independently security audited. Work only on projects and targets you own or are authorized to use.
