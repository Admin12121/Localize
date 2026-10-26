# Web-Bridge companion

**Python 3.10+ · Windows / macOS / Linux · Web-Bridge 3.1.1**

This is the local half of [Web-Bridge](../README.md). It exposes authenticated RPC to your private Site and keeps project selection, permissions, CTF target approvals, and host-command approvals on your computer.

## Run the single-file bundle

Install Python and the official [cloudflared](https://developers.cloudflare.com/tunnel/downloads/) binary. The bundle does not need extraction or `pip install`.

```powershell
# Windows
python Web-Bridge.pyz
```

```sh
# macOS / Linux
python3 Web-Bridge.pyz
```

The bundle starts its authenticated Cloudflare Quick Tunnel by default. To avoid creating a tunnel, run `python Web-Bridge.pyz --local-only` (or `python3` on macOS/Linux).

A source installation can run `python bridge/launch.py --tunnel` from the source root, or `python launch.py --tunnel` from inside `bridge/`. On Linux/macOS use `python3`.

The terminal prints the **local control panel address**, a one-time **local control code**, a remote **Site /mcp endpoint**, and a **Site connection key**. Enter the control code only in your locally opened panel. Store the endpoint and connection key only in your private Site's connection settings. Keep the companion running while you use ChatGPT.

Check `--help` for `--target`, `--runtime`, `--rpc-port`, `--control-port` and `--no-browser`.

## Local permissions

| Capability | Owner action |
| --- | --- |
| CTF HTTP | Approve each exact website origin, including private lab networks when needed |
| Workspace | Select one project folder; grant read/search and optional text edits |
| Container execution | Enable execution, prepare and select a supported Docker image |
| Host execution | Opt in locally, then approve each command's exact arguments |
| Browser | Install optional Playwright and Chromium |

You can pause/revoke locally. Permission changes invalidate pending operations. File edits already applied cannot be undone by pausing.

The control UI stays on **loopback**; do not tunnel its port. The authenticated RPC listener is a separate process endpoint. HTTP redirects are not followed; target requests are constrained to locally approved origins. Site tools cannot grant permissions or approve jobs.

## Commands and isolation

**Container mode:** Install and start Docker with Linux-container support, then prepare a supported image (for example `docker pull python:3.12-alpine`). Commands work on a filtered project copy, not a bind mount of the original folder. The container root filesystem is read-only, but the staged project copy is writable. Eligible text diffs are applied to the original only through the configured approval/write policy. Deletions and missing parent directories are not applied. Each job uses a new container; persistent project environments and existing-container attachment are not available. Enabling container networking separately allows outbound traffic and may transmit staged source.

**Host mode:** Runs with your OS account, not inside a sandbox. Selected folders do **not** limit which files a host command can access. Each command requires specific, single-use local approval. Cancellation attempts to terminate the owned process group; processes or services outside that ownership still need separate verification. A successful CLI exit does not prove a desktop window opened or a service became healthy.

Jobs last up to 120 seconds, return at most 64,000 bytes of combined stdout/stderr, and the current session retains up to 30 jobs. Commands are queued once and polled by job ID; do not resubmit pending jobs. `pending` is awaiting approval and `approved` is queued to start, not proof that execution finished. **Known issue:** `completed` can accompany a nonzero exit code. Check the exit code, output and requested effect.

## File tools and state

Workspace tools support bounded UTF-8 reads and edits (256 KB/file), literal search and up to 500 listed entries per directory. Staged snapshots are limited to 5,000 entries/50 MB, with up to 20 eligible text-change proposals. They exclude symlinks, junctions, credentials, `.git`, dependencies, private-key patterns, and runtime state. File-tool deletion, directory creation, and arbitrary binary modification are not supported.

For the single-file bundle, runtime credentials persist separately from its temporary unpacked code:

- Windows: `%LOCALAPPDATA%/Web-Bridge/runtime`
- macOS: `~/Library/Application Support/Web-Bridge/runtime`
- Linux: `$XDG_STATE_HOME/web-bridge` or `~/.local/state/web-bridge`

Use `--runtime .runtime` when intentionally reusing an older source installation's runtime. Stop the old instance first. Permissions reset on restart; Quick Tunnel URLs can change, so update the Site endpoint without unnecessarily changing the existing key. Never upload runtime files.

## Optional browser

```sh
python -m pip install playwright
python -m playwright install chromium
```

The browser operates within approved origins. Browser and HTTP cookies are separate; browser downloads, WebSockets and service workers are blocked.

## Verify from ChatGPT

Select your **own Site-generated plugin** and run `bridge_status`, then one explicitly authorized workspace read or local CTF request. Confirm returned evidence. Installing a plugin or publishing a Site does not by itself prove that the local companion is connected.

Full developer documentation is in the canonical source repository: `README.md`, `ARCHITECTURE.md`, and `SECURITY.md`. (These files are not bundled into the standalone companion ZIP.)

## Operational guides and planned upgrades

In a full source checkout, see [Usage](../docs/usage.md), [Troubleshooting](../docs/troubleshooting.md) and [Setup](../SETUP.md). These source guides are not bundled into the standalone companion ZIP. They explain current Docker preparation, the difference between approval/execution/application, and the known command-outcome issue.

Folder creation, rename/delete tools, persistent Docker project access, local skill/MCP/application adapters and durable task continuation are proposed upgrades, not features of this bundle. Keep the companion and its grants available while ChatGPT works; restarting does not resume a saved task or previous job.
