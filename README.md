# Web-Bridge

**A private, owner-controlled connection between ChatGPT and your local computer.**

Web-Bridge consists of an authenticated MCP gateway deployed to a private ChatGPT Site and a Python companion running on Windows, macOS, or Linux. It enables ChatGPT to inspect explicitly selected projects, submit file edits, test authorized web applications, and request bounded commands. The owner controls access through a separate local panel.

**Version:** 3.1.1 · **Author:** [admin12121](https://github.com/Admin12121) · **License:** MIT

## How it works

```text
ChatGPT + Site-generated MCP plugin
              │
              ▼
Private Site gateway (worker/runtime.js)
              │  authenticated HTTPS
              ▼
Cloudflare Tunnel (optional remote transport)
              │
              ▼
Python companion on 127.0.0.1
     ├── HTTP/browser → approved origins only
     ├── Files → selected workspace only
     ├── Docker → isolated project snapshot
     └── Host commands → exact local approval

Separate local control panel: permissions, targets, job approval, pause
```

The public tunnel exposes only authenticated RPC—not the local control panel. Workspace selection, CTF allowlists, command approval and revocation are enforced by the companion. Host commands are **not confined to the selected folder** and require explicit approval.

## Run the companion

Install **Python 3.10+** and [cloudflared](https://developers.cloudflare.com/tunnel/downloads/). Download the release asset `Web-Bridge.pyz`. The core companion needs no pip installation or extraction.

```powershell
# Windows
python .\Web-Bridge.pyz
```

```sh
# macOS / Linux
python3 Web-Bridge.pyz
```

The bundle starts a tunnel by default; add `--local-only` to disable it. The terminal prints a **local control code**, a **Site endpoint**, and a **connection key**. Open the printed local panel, choose the project and permissions, then enter the endpoint/key only in your **private Site connection page**. Keep secrets out of chats, screenshots and Git.

To create your own Site, use the release setup plugin in an account with Sites and plugin-creation access. The plugin requires an explicit deployment workflow; importing it alone does not create a Site.

Finally, select your Site-generated plugin in ChatGPT, call `bridge_status`, and verify an approved file read or HTTP request.

## Capabilities and boundaries

| Feature | Available | Limitation |
| --- | --- | --- |
| HTTP & CTF labs | Requests, form inspection, cookies, request history | Exact approved origins; no automatic redirects |
| Workspace | List, search, read and edit UTF-8 text | Scoped selection, file-size limits, diff policy |
| Container commands | Docker with filtered source snapshot | Docker engine and pre-pulled approved image required |
| Host commands | Real OS process execution | Individual approval; unrestricted host permissions |
| Optional browser | Scoped Chromium actions | Requires Playwright/Chromium locally |

This version does **not** provide full desktop input/control, persistent interactive terminal sessions, arbitrary binary-file editing, or autonomous Docker provisioning.

## Source and development

This checkout currently includes the distributable folders `Companion/`, `Plugin/` and `Web-Bridge.pyz` alongside the **canonical development source in `source/`**. These distributions are generated artifacts; do not edit their copies independently. The source tree builds the companion, hosted worker, Site setup plugin and sanitized releases.

```sh
cd source
npm ci
npm run check:repo
npm run build
npm run validate
npm test
python -m pytest -q bridge/tests
python scripts/package-release.py
```

Requires Node.js 22.13+ and Python 3.10+; install pytest for Python tests. Outputs are generated under `source/dist/` and `source/outputs/`. Use `python scripts/export-repository.py` from `source/` to produce a source-first GitHub checkout, and release binaries as downloadable assets instead of committing copies.

## Security and disclosure

Only connect to applications and projects you own or are authorized to test. Never tunnel the local control port or commit Site connection credentials, runtime folders, tunnel logs or private workspace files. Network-enabled containers can transmit the staged source, and host commands can access anything available to the OS account.

See [SECURITY.md](source/SECURITY.md) for reporting. This project has not been independently audited.

**MIT License** · Copyright (c) 2026 admin12121.
