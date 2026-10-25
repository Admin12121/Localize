# Web-Bridge

**Created and maintained by admin12121 · MIT license · Windows / macOS / Linux**

A private ChatGPT Site gateway and a locally controlled Python companion for authorized CTF websites and local coding. The existing application display name is **Admin12211's Web-Bridge instance**.

- CTF mode: explicitly approved website origins, HTTP requests, HTML inspection, cookies, browser tools, and request evidence.
- Local coding: select a project, read/search files, review text edits, and request commands.
- Control stays local: exact host-command approval; optional Docker execution against a filtered copy.
- Compact command history with expandable output and live status updates.

## Quick start

### 1. Create your own private ChatGPT Site

Download `Web-Bridge-Setup-Plugin.zip` from this repository's release assets. In your own account, attach the ZIP to a Sites-enabled build chat and ask:

> Install the attached Web-Bridge Setup plugin and use it to create my own private Web-Bridge Site and canonical plugin. Use fresh account-owned IDs and secrets, and keep the Site owner-only. Then show my companion download and connection steps.

Where plugin ZIP import is offered, you can import the setup ZIP first and explicitly invoke **Web-Bridge Setup**. Installing it alone does not deploy a Site. Each recipient creates their own private Site and connection; do not use another person's endpoint or keys.

Initial setup requires Sites, plugin creation, and file/build tools in the recipient's account. If these are unavailable, the package cannot enable them. Availability and workspace policy vary; universal installation on every ChatGPT account is not guaranteed. See [OpenAI Plugins](https://learn.chatgpt.com/docs/plugins) and [Sites](https://learn.chatgpt.com/docs/sites).

### 2. Start the companion

Install Python 3.10+ and [cloudflared](https://developers.cloudflare.com/tunnel/downloads/) once. Download `Web-Bridge.pyz` from your own Site or this repository's release assets. Open a terminal in its folder:

| Windows | macOS / Linux |
| --- | --- |
| `python Web-Bridge.pyz` | `python3 Web-Bridge.pyz` |

No manual extraction or pip install is needed for core features. The authenticated tunnel starts by default. Keep the terminal open. Add `--local-only` to disable the public tunnel. Docker is optional, required only for isolated commands. Optional browser tools need Playwright and Chromium.

### 3. Connect and choose access

Unlock the local panel with the terminal's **local control code**. Add authorized website URLs, or select a project and permissions. In **your private Site**, save the terminal's **Site endpoint** and **Site connection key**, then test. Keep codes and keys out of chat.

Select your Site-generated plugin in a new ChatGPT conversation and ask it to call `bridge_status`. Confirm an approved file read or CTF request before relying on access.

## Public project metadata

Author / creator: **admin12121**. License: [MIT](LICENSE). Software version: **3.1.1**. Setup-plugin version: **1.1.1**.

`python Web-Bridge.pyz --about` prints public project metadata without starting servers. `--version` prints the version and creator. The local panel and bridge status also show attribution.

## Build and publish your GitHub release

Requires Node 22.13+ and Python 3.10+. The Worker has no runtime npm dependencies. Run:

```sh
node scripts/build.mjs
node scripts/validate-artifact.mjs
npm test
python scripts/package-release.py
```

Outputs include `Web-Bridge.pyz`, companion ZIP, setup-plugin ZIP, sanitized source ZIP, release ZIP, and `SHA256SUMS`. Upload the **contents of the sanitized source ZIP** as your repository source, and attach release artifacts separately. The source ZIP has no `.git` history, Site project ID, keys, connection settings, or local runtime state. Keep the generated build and runtime folders out of Git.

For Python verification, install pytest in your development environment and run `python -m pytest -q bridge/tests`. Optional real Docker tests use `WEB_BRIDGE_DOCKER_TEST=1` with an already prepared `node:24-alpine` image. Schema development dependencies are needed only for schema changes; preserve migrations.

Fresh Site deployments generate a fresh `CONFIG_ENCRYPTION_KEY` (32 random bytes, base64), retain the D1 database binding and MCP capability, and use the supported Sites workflow. Existing deployments preserve identity, database, secret, and audience. Read [SETUP.md](SETUP.md) and [companion details](bridge/README.md).

## Limits and related work

Permissions and command history last for one companion run. History retains 30 jobs, output is capped at 64 KB, and commands at 120 seconds. Host execution can access outside the selected project; selecting a folder alone does not confine commands. Desktop-control and interactive-terminal APIs are not included.

Similar projects already exist. See [RELATED-PROJECTS.md](RELATED-PROJECTS.md); this project makes no first-of-its-kind claim.

## Contributing and reporting

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Distributed under the MIT license; retain its copyright and permission notice when redistributing. External prerequisites retain their own licenses.


