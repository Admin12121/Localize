# Web-Bridge

Web-Bridge connects a private ChatGPT Site to an owner-controlled local companion. It exposes selected project files, approved web targets, and gated command execution through MCP without granting ChatGPT unrestricted access to the host.

Built for local development and authorized security labs. Runs on Windows, macOS, and Linux.

## How it works

```text
ChatGPT → private Site (MCP worker) → authenticated HTTPS tunnel
                                          │
                                          ▼
                              Python companion (localhost)
                               ├─ approved HTTP targets
                               ├─ scoped workspace tools
                               └─ approved Docker / host commands
```

The Site forwards tool calls; the companion enforces permissions. Project selection, target allowlists, host-command approvals, and revocation remain in a separate local control panel.

## Setup

**Requirements:** Python 3.10+ and [cloudflared](https://developers.cloudflare.com/tunnel/downloads/) for remote connection. Docker is optional for isolated command execution. Playwright/Chromium is optional for browser tools.

1. **Provision your own private Site.** Use the `Web-Bridge-Setup-Plugin.zip` release asset in a ChatGPT account that supports Sites, plugin creation and build tools. The setup workflow creates an account-owned Site with new secrets. Importing the plugin alone does not deploy anything.
2. **Start the companion.** Download `Web-Bridge.pyz` from your Site or a trusted release. No extraction or `pip install` is required for its core features.
3. **Connect privately.** Open the local control panel URL printed in the terminal. Enter its local control code and configure allowed targets, project folder, and permissions. Paste the Site endpoint and connection key **only** into your private Site's connection form.
4. **Verify.** Select the Site-generated plugin in a ChatGPT chat, invoke `bridge_status`, then test one authorized read or HTTP request.

```powershell
# Windows
python .\Web-Bridge.pyz
```

```sh
# macOS or Linux
python3 Web-Bridge.pyz
```

The single-file companion starts an authenticated Quick Tunnel by default. Add `--local-only` to avoid starting it. A source installation can run `python bridge/launch.py --tunnel` from the repository root.

Upgrading from the older source-ZIP companion? Stop the old process, then run `python Web-Bridge.pyz --runtime .runtime` from its previous directory to reuse that installation's key. Permissions reset at restart, and Quick Tunnel URLs may change. Update the endpoint in your private Site without disclosing keys in chat.

## Capabilities

| Area | Available operations |
| --- | --- |
| HTTP labs | Exact-origin allowlist, requests, forms, cookies, bounded evidence, optional Chromium |
| Workspace | List, search, read and propose UTF-8 text edits inside a selected project |
| Commands | Bounded jobs, output/status polling, Docker isolation or exact-approved host execution |
| Local controls | Permission selection, diff/command approvals, pause and revocation |

Host commands can access files beyond the selected project. They require local approval for each exact command and are **not sandboxed**. Docker commands use a filtered staged copy; Docker network access is a separate opt-in. Never tunnel the local control panel.

**Not included:** desktop mouse/keyboard control, interactive terminal sessions, unrestricted filesystem APIs or automatic host privilege escalation.

## Develop

Node.js 22.13+ is required for building the Site worker. Python 3.10+ is required for packaging the companion.

```sh
npm ci
npm run check:repo
npm run build
npm run validate
npm test
python -m pytest -q bridge/tests  # optional: install pytest first
python scripts/package-release.py
```

Build output is written to `dist/` and `outputs/`. To export a GitHub-ready source checkout, run `python scripts/export-repository.py`; it creates `outputs/github-repository/` and does not overwrite an existing directory. Publish the **contents of that directory**, not the extracted release wrapper. Attach `.pyz` and ZIP distributions as GitHub Release assets.

```text
bridge/         Python companion, control panel and local RPC
worker/         Private Site interface and MCP gateway
db/, drizzle/   Database schema and migrations
setup-plugin/   Account-owned Site setup workflow
scripts/        Packaging, verification and source export
tests/          Worker tests; bridge/tests/ holds Python tests
```

## Security

The local control listener must remain on loopback. Keep Site connection keys, local control codes, tunnel runtime logs and workspace data out of Git and public issues. Host execution and container networking can access sensitive data beyond the filtered workspace; enable them only when needed.

See [SECURITY.md](SECURITY.md) for threat boundaries and private reporting. This software has not been independently security audited.

## License

[MIT](LICENSE) · Copyright (c) 2026 admin12121.
