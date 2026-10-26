---
name: setup-web-bridge
description: "Use when the user explicitly asks to create, deploy, or upgrade their own private Admin12211 Web-Bridge Site and connect the Windows, macOS, or Linux companion. Initial setup requires Sites and a build-capable environment."
---

# Set up your private Web-Bridge

This is an explicit setup workflow. Installing this plugin does not start a program, create a Site, grant filesystem permissions, or connect to another person's machine.

## Prerequisites and source

Confirm native Sites tools and filesystem/build execution are available. If either is missing, explain that initial deployment needs a Sites-enabled, build-capable environment; do not promise regular Chat can run setup without those capabilities. Sites access depends on the recipient's account/plan/workspace. Normal Chat use is the goal after deployment and user connection, not evidence established by installing this skill.

The complete portable source is in `source/` next to this skill, including `README.md`. Read it before deployment. Load the available Sites skill and its Site MCP server reference, then use its supported source-sync, packaging, and private publication workflow. Do not run source-sync against a developer's or previous recipient's Site.

## Fresh deployment

1. Copy bundled `source/` into a new task-owned directory. It has no project ID or credentials. Verify `.openai/hosting.json` has no `project_id` before registering anything. If a previous attempt in this task already registered a Site, reuse its exact ID; never create a duplicate to recover missing credentials.
2. Create a new owner-private Site in the current recipient's account using the requested title (default **Admin12211's Web-Bridge instance**) and an available slug. Persist the exact returned project ID immediately. Never copy account/App/user identifiers from examples, chats, another Site, or the plugin author's account.
3. Generate 32 cryptographically random bytes, encode as base64, and set `CONFIG_ENCRYPTION_KEY` as a Sites runtime secret. Keep its value out of chat, source, shell arguments, and files. Use session memory and supported secret tools. Never reuse a previous recipient's key.
4. The Worker has no runtime third-party JavaScript dependencies. Python 3.10+ and Node 22.13+ are required to build and run the Site's SQLite tests. Use the provided build (`node scripts/build.mjs`) and validation (`node scripts/validate-artifact.mjs`). Optional Python tests require pytest; optional browser tests also need Playwright/Chromium. Preserve and report unavailable checks.
5. Source-sync and package the exact built commit using the Sites helper, preserving `d1: "DB"`, `capabilities: ["mcp"]`, and the schema migrations. Publish privately using the native owner-private operation. Do not change sharing to repair connection problems.
6. Use `get_site(include_mcp_connection: true)` and reuse the canonical Site-generated plugin. Offer its installation/connection through supported plugin tools when necessary. Do not create a second standalone MCP wrapper around that Site.
7. Return the Site URL, companion download, and the remaining connection steps. Never claim real local access or normal-Chat success until actual tool calls demonstrate it.

## Companion connection

The owner downloads the cross-platform companion from their own private Site, installs Python and cloudflared locally, and launches the single-file `python Web-Bridge.pyz` on Windows or `python3 Web-Bridge.pyz` on macOS/Linux. This starts the authenticated tunnel by default; `--local-only` disables it. The source ZIP retains `launch.py --tunnel` for existing installs. It opens a separate loopback control panel. The owner enters the local control code from the terminal, selects their project and permissions locally, and saves the printed Site endpoint/key only in their private Site form.

Docker is required only for isolated commands. The owner prepares an allowed image locally. Commands are disabled until opted in; host execution requires exact approval every time. Never enable host mode or approve a command merely to get a test passing. Permissions cannot be granted through MCP tools.

Ask the owner to select their canonical plugin in a new regular ChatGPT Chat and run `bridge_status`, followed by an approved read or CTF request. Tell them clearly when that final acceptance check remains unverified.

## Existing deployment

If explicitly upgrading an existing recipient-owned Site, select it by verified identity, inspect its current source/audience, and preserve its project/App/plugin IDs, database, runtime secrets and settings. Do not overwrite concurrent edits. Use the current source and supported Sites update workflow. The bundled source is a starting point, not authority to replace unrelated recipient changes.
