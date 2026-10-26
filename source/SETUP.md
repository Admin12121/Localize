# Set up Web-Bridge

[README](README.md) · [Usage](docs/usage.md) · [Troubleshooting](docs/troubleshooting.md)

This guide describes **version 3.1.1**. Each owner uses their own private Site and local companion. Existing-container attachment and a Docker setup wizard are proposed upgrades, not steps available in this release.

## Requirements

| Component | When needed |
| --- | --- |
| ChatGPT account/workspace with Sites, plugin creation and build/file tools | Provisioning your private gateway; availability depends on the account |
| Python 3.10+ | Running and packaging the companion |
| [cloudflared](https://developers.cloudflare.com/tunnel/downloads/) | Default remote connection from the private Site |
| Local Docker engine using Linux containers | Container commands only |
| Local Playwright and Chromium | Optional browser actions only |
| Node.js 22.13+ | Building/developing the Site source |

## 1. Provision your private Site

Use the trusted `Web-Bridge-Setup-Plugin.zip` release asset in a build-capable Sites chat. Where plugin ZIP import is supported, import it and invoke **Web-Bridge Setup** explicitly. A request such as “Use Web-Bridge Setup to deploy my own private Site from this package and return its generated plugin” identifies the intended workflow.

The workflow copies sanitized source, creates an account-owned private Site, configures a fresh encryption secret, builds/publishes it, and returns that Site's generated plugin. Importing the setup package by itself does not deploy anything. If a required account capability is unavailable, report it rather than connecting to another owner's private Site.

## 2. Start your companion

Download `Web-Bridge.pyz` from your trusted release or private Site. The core bundle needs no pip installation or extraction.

```powershell
# Windows
python .\Web-Bridge.pyz
```

```sh
# macOS / Linux
python3 Web-Bridge.pyz
```

The bundle starts a Quick Tunnel by default. Add `--local-only` to disable tunneling. For development from this source directory, run `python bridge/launch.py --tunnel` instead; the source launcher only starts a tunnel when requested.

Keep this process running. The terminal prints a local control panel address/code and a remote Site endpoint/connection key. These are different credentials with different purposes.

## 3. Select the local project and permissions

Open the printed loopback control panel and sign in with its local control code. Choose a project directory and a friendly alias. Start with read/search, then enable text writes and command requests if needed.

Optional session writes apply eligible text changes without approving every proposal. Host command execution remains separately enabled and requires exact local approval for every command. Pause revokes current access and pending work; it does not undo already applied changes. Configuration changes revoke existing approvals and replace the workspace ID.

Never expose the control panel through the tunnel. The authenticated RPC endpoint is the only remote transport endpoint.

## 4. Prepare Docker if you want container commands

Start Docker Desktop in Linux-container mode or a local Linux Docker engine. In a local terminal, verify readiness:

```sh
docker info --format '{{.OSType}}'
docker pull node:24-alpine
docker image inspect node:24-alpine
```

The first command should report `linux`. Select `node:24-alpine` under isolated commands in the companion panel and enable command requests. You can instead prepare/select `python:3.12-alpine` or `alpine:3.21`. The bridge checks that the selected image exists and uses its inspected image ID. It does not pull an image automatically or fall back to host execution.

Each Docker command creates a fresh container with a filtered project copy. There is no persistent project-container connection to configure in 3.1.1. Files in the original project change only when eligible proposals are applied. Dependencies and Git data are excluded from snapshots; ordinary full-project builds may therefore need additional preparation and may exceed the 120-second limit. See [Docker troubleshooting](docs/troubleshooting.md#docker-commands).

## 5. Connect the Site

Open your private Site's connection page. Paste the **remote HTTPS Site endpoint** and **connection key** printed by your companion into that form. Do not paste them into chat, issues, Git, or screenshots. A localhost control URL is not a remote Site endpoint.

Select your Site-generated plugin in ChatGPT. Call `bridge_status`, check its version, workspace, permissions and pause state, then use its current `workspace_id` for workspace operations.

## 6. Verify actual behavior

1. Read a small known project text file and compare its contents.
2. Submit a harmless print command in the intended environment using the [usage examples](docs/usage.md).
3. Approve it locally if required and poll its returned job ID.
4. Check exit code, output and the requested effect. `pending` or `approved` is not execution; `completed` can currently contain a nonzero exit code.
5. If testing a file edit, approve it and read the file back from the real workspace. A proposed edit or Docker snapshot result alone does not prove synchronization.

## Update an existing installation

Stop the companion with Ctrl+C, replace its bundle, then restart. To reuse an older source/ZIP installation's runtime key, run the new bundle from the old folder with `python Web-Bridge.pyz --runtime .runtime` (`python3` on macOS/Linux).

Permissions must be selected again. Quick Tunnel URLs can change at restart; update the Site endpoint. Leave the connection key field blank to retain the saved key when it is unchanged. Keep an existing private Site's identity, encryption secret and database when upgrading that deployment; use new identity/secrets for a new owner's deployment.

## Source export and privacy

From the source root, run the development checks in [CONTRIBUTING](CONTRIBUTING.md), then use `outputs/web-bridge-portable-source.zip` or `python scripts/export-repository.py` for sanitized source. Portable hosting configuration omits the original project ID. Runtime state, selected project data and credentials must never enter releases.

For a supported tool's limits or unexpected results, use [Usage](docs/usage.md) and [Troubleshooting](docs/troubleshooting.md). Proposed future behavior is described separately in [Upgrade direction](docs/roadmap.md).
