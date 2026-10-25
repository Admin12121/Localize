# Admin12211's Web-Bridge instance — companion 3.1.1


Created by **admin12121** · **MIT license**. Use `--about` to inspect public project metadata, or `--version` for the version and creator.

Use your account's private Web-Bridge Site with this Windows/macOS/Linux Python companion. Do not connect the former standalone CTF archive to this Site.

## Start

Install Python 3.10 or later and the official Cloudflare `cloudflared` executable. On Windows, `winget install Cloudflare.cloudflared` is one installation option; on macOS, `brew install cloudflared` is another. Linux users should use Cloudflare's official package for their distribution. The launcher does not install these prerequisites or privileged services.

Download **Web-Bridge.pyz** into any folder. No extraction or pip install is needed. Open a terminal in that folder and run:

```powershell
# Windows
python Web-Bridge.pyz
```

```sh
# macOS / Linux
python3 Web-Bridge.pyz
```

The single-file launcher starts the authenticated tunnel by default. Add `--local-only` for local use. It unpacks code into a temporary folder for this run, with credentials kept separately in `%LOCALAPPDATA%/Web-Bridge/runtime` on Windows, `~/Library/Application Support/Web-Bridge/runtime` on macOS, and `$XDG_STATE_HOME/web-bridge` (default `~/.local/state/web-bridge`) on Linux. Replacing the bundle does not replace runtime credentials.

For an existing source-ZIP install, the existing `python launch.py --tunnel` and `start.ps1` / `start.sh` still work. To use your existing key with the bundle, stop the old companion, place Web-Bridge.pyz in its folder, and run `python Web-Bridge.pyz --runtime .runtime` (use python3 on macOS/Linux). Re-select project permissions after restart and update the Site endpoint.

The launcher opens a separate loopback control panel and prints a local control code. Enter that code in the local panel. The terminal also prints the tunnel `/mcp` endpoint and a Site connection key. Save those only in your private Site's Connection form, then select Test companion. Never paste either code/key into ChatGPT or a URL.

For the source launcher only, `python launch.py` without `--tunnel` starts local controls and authenticated local RPC without public exposure. The single-file bundle starts a tunnel by default; use `python Web-Bridge.pyz --local-only` (python3 on macOS/Linux) for local-only use. `--target https://challenge.example:8443` can initialize one exact authorized CTF origin. More targets can be configured in the local control panel. `--runtime`, `--rpc-port`, `--control-port`, and `--no-browser` are available for explicit local customization; see `--help`.

Keep the terminal running. Ctrl+C stops the companion and its owned tunnel/jobs. Quick Tunnel addresses change after restart: update the Site endpoint and leave its key field blank to keep the saved key. The local-control code changes on restart; the separate Site connection key persists in the protected runtime directory. For source-ZIP launches this is `.runtime` beside launch.py; for the bundle use the platform-specific runtime directory listed above, or your explicit `--runtime` path. To rotate while stopped, remove only `site-connection-key` from that runtime directory, restart, and replace the saved key privately in the Site.

## Choose local access

CTF and coding are separate locally enforced modes. No MCP tool can select a filesystem root, grant permissions, approve host commands, or change network policy.

- CTF: approve exact scheme/host/port origins locally. Private lab addresses require explicit opt-in. Redirects are not followed; DNS is pinned and environment HTTP proxies are disabled.
- Coding: choose one project folder locally, by picker or local path entry. Grant file reads, proposed writes, and command requests separately. Default file writes require local diff approval. A separate checkbox permits direct text edits during the current session.
- Pause/revoke prevents new operations, invalidates pending approvals, and cancels managed command jobs. Permission changes revoke old jobs and edits. File edits already applied cannot be undone merely by pausing.
- Files sent through tools travel through the private Site and tunnel to ChatGPT. Share only intended project code.

Permissions reset when the companion restarts. The companion does not auto-start on login. Only its authenticated RPC port is tunneled; never manually tunnel the local control port.

## Container commands

Install Docker with Linux-container support. Prepare one supported image locally before requesting a command:

```sh
docker pull python:3.12-alpine
# alternatives: node:24-alpine, alpine:3.21
```

Select the prepared image in local controls. The companion does not pull a model-selected image or fall back to host execution.

Container commands use a filtered copy of the selected project, not a bind mount of the original folder. The container runs non-root with a read-only base, dropped capabilities, resource limits, scratch storage, and networking off by default. Commands may change their staged copy. Eligible changes return as local diff approvals; originals are updated only after approval or the explicit session-write grant. Deletions and unsupported binary changes are not automatically applied.

Enabling container networking permits ordinary outbound traffic and may transmit all approved staged source and output. It is a separate local permission, not CTF-origin filtering. Without networking, dependencies must already be in the selected image. Containers are an isolation layer, not a guarantee against every runtime/kernel vulnerability.

## Host commands

Host mode is optional and requires a separate local opt-in. Every command still needs exact local approval of its executable, arguments, working directory and timeout. Approvals expire and are single-use. The model queues a job, then reads status rather than resubmitting commands.

Host commands use your OS user and may access beyond the project, read excluded files, use host networking, and modify files without a diff preview. They are not isolated. A selected working directory is not confinement. Only grant an exact command when you accept that access. No automatic elevation is provided. Detached child processes may outlive best-effort host cancellation; stop such processes using your OS tools when necessary.

## Limits and exclusions

The first version provides bounded UTF-8 reads and edits (256 KB/file), literal text search, up to 500 entries per directory, and 5,000 entries/50 MB per filtered snapshot. Text edits create/update files in existing directories; file deletion and directory creation are not exposed as file tools. Command jobs are limited to 120 seconds, 64 KB returned output and 30 jobs/session. Up to 20 pending edits are retained for five minutes. Batches retain their existing CTF limits.

File tools and snapshots exclude `.git`, `.env*`, private-key patterns, credential folders, dependency directories, runtime state, symlinks and junctions. Exclusions are fixed in this version. Commands inside a container cannot read files absent from its staged copy. Host commands are not constrained by these exclusions.

Snapshot diffs propose at most 20 changed UTF-8 files. Unsupported, excluded, conflicting or oversized changes are not applied. History and jobs are session-local. HTTP cookies and optional Chromium sessions remain separate.

## Optional browser

In a Python virtual environment on the computer running the companion:

```sh
python -m pip install playwright
python -m playwright install chromium
```

Use `python3` where appropriate. Linux may require Chromium OS dependencies and non-root sandbox support. Browser tools retain approved-origin mediation. Browser WebSockets, service workers and downloads are blocked. HTTP multipart uploads and bounded binary responses remain available.

## Regular Chat acceptance

Select your Site-generated plugin in a new regular ChatGPT conversation. Ask it to call `bridge_status`, then an approved `workspace_list`/`workspace_read` or CTF `list_targets`/`http_request`. Confirm actual tool cards and real responses. Publishing the Site and installing its plugin do not alone prove regular-Chat compatibility.

For another account, use the reusable setup package to explicitly create that account's own private Site with new secrets. The recipient needs Sites and a build-capable environment for initial setup; installing a ZIP does not automatically provision hosting.

## Activity and live updates (3.1)

Command rows start collapsed. Expand to fetch exact arguments and output. Scroll the fixed-height list for more retained rows; Load more also works with a keyboard. The session still has its existing 30-command limit. Approvals display exact arguments and settings before Accept/Decline becomes available.

While visible, local state checks run every 750 ms without overlapping. Unchanged responses have no body. Hidden tabs stop polling. Full output and edit diffs load on demand. The private Site refreshes status every 10 seconds while visible; model/tool and tunnel round-trip times still depend on the network.
