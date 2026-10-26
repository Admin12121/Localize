# Web-Bridge companion

**Version 3.2.0 · Core Python 3.10+ · Windows / macOS / Linux**

The local half of [Web-Bridge](../README.md) exposes authenticated RPC to your private Site while project selection, grants, approvals, Docker setup and optional task-runner controls stay on your computer.

## Launch

Install Python and official [cloudflared](https://developers.cloudflare.com/tunnel/downloads/). Core bundle features require no extraction or pip packages:

```powershell
# Windows
python Web-Bridge.pyz
```

```sh
# macOS / Linux
python3 Web-Bridge.pyz
```

The bundle starts a Quick Tunnel by default; `--local-only` disables it. From a source root use `python bridge/launch.py --tunnel`; inside this folder use `python launch.py --tunnel`. Source launches tunnel only when requested. Use `python3` on macOS/Linux where needed.

The terminal prints a local panel/code and remote Site endpoint/key. Enter the control code only in the loopback panel and save the remote endpoint/key only in your own private Site form. Keep the process running. Never tunnel the control panel.

`--help` lists `--target`, `--runtime`, `--rpc-port`, `--control-port`, `--no-browser`, `--version` and `--about`. `--target` selects one explicitly approved website origin; more can be configured locally.

## Local controls

| Control | Behavior |
| --- | --- |
| Project/read/write | Selected folder; read/search, proposed text edits and nested creates |
| Folder operations | mkdir, move, recoverable delete/restore; separate session approval and recursive-delete grant |
| Command profile | Host, snapshot or live Docker; installed shell; 600-second default/at most 3,600-second maximum |
| Host | Separate enable plus exact approval every time; OS-account access beyond the project |
| Container command approval | Optional session grant for snapshot and live Docker commands |
| Docker project | Local context/image/mapping, check, explicit pull/create/attach, owned-container lifecycle/logs |
| Integrations | Selected skill folders and allowlisted stdio/HTTP MCP application tools |
| Saved work | Durable tasks, checks, handoff, local **Use in ChatGPT** rebinding, **Confirm reviewed complete**, and optional runner start/cancel |
| Pause | Revoke access and stop current work; does not undo applied effects |

Saving permissions invalidates the workspace ID and pending grants/proposals/jobs. Grants reset on restart. Tools cannot grant themselves access or approve their own requests.

## Command and Docker boundaries

Use `command` plus configured shell for ordinary terminal syntax, or `argv` for exact executable arguments; never both. Windows npm/npx batch launchers should use `command` with `shell: "cmd"`; direct batch argv is rejected. Omitted environment follows the local profile, and a conflicting explicit environment is rejected. Host commands receive a minimal environment.

Snapshot Docker uses a filtered copy of the project, not a real-project mount; its root is read-only and stage writable. Supported pre-pulled images are `python:3.12-alpine`, `node:24-alpine` and `alpine:3.21`. Networking is separately granted. Eligible creates/edits/deletes become proposals under the applicable text/operation policy. Unsupported, excluded, conflicting and over-limit changes are reported; unresolved artifacts are retained locally, capped at ten, with local inspect/discard controls.

Live Docker uses a persistent container mapped to the selected real project. Save/check local setup, explicitly prepare an image and create or validate attachment. Context/endpoint and mapping are pinned, socket exposure is rejected, and broader attached configurations require local inspection/acknowledgment where applicable. Commands write shared files directly. Stop/remove only affects bridge-owned containers; per-exec cancellation targets command groups rather than unrelated container work.

Submit once with an idempotency key and poll the job ID. `pending`/`approved` are not execution success. Nonzero exit is `failed` with `success: false`; timeout and cancellation differ. Inspect launch evidence, output, exit code, `success`, `cleanup_pending` and the intended effect. Output is bounded to 64,000 bytes with incremental character offsets. Up to 30 jobs may be active. The dashboard retains 200 compact rows and the newest 160 detailed durable receipts, with older identity/idempotency tombstones. Restart preserves inspection-only receipts; potentially unfinished executions require local stopped/reviewed confirmation before new writes.

## Files, tasks and private runtime

Text files are limited to 256,000 bytes; snapshots to 5,000 entries/50 MB. Sensitive paths, links, credentials, Git/dependency/runtime data are excluded from file/snapshot tools. These filters do not constrain approved host or real-project Docker commands.

File writes use hashes and platform-safe publication. Recoverable deletion retains excluded project trash and runtime restore records. A POSIX text-write `recovery_path` preserves original-inode data, including possible later writes from existing external descriptors; inspect locally before cleanup. Do not publish recovery artifacts.

For the single-file bundle, runtime data lives separately from temporary extracted code:

- Windows: `%LOCALAPPDATA%/Web-Bridge/runtime`
- macOS: `~/Library/Application Support/Web-Bridge/runtime`
- Linux: `$XDG_STATE_HOME/web-bridge` or `~/.local/state/web-bridge`

Use `--runtime .runtime` only when intentionally reusing an older source installation's runtime; stop its old process first. Connection keys, task SQLite state and selected integration/Docker configuration persist. Grants and active execution state reset; durable command receipts remain available for local inspection. Quick Tunnel URLs may change; update the private Site endpoint without unnecessarily changing its saved key. Runtime state can contain credentials/private source and must never be uploaded.

Saved tasks preserve checks, evidence and handoff, not automatic mutation replay. ChatGPT resumes on the next prompt; after a new session choose **Use in ChatGPT** locally. Automatic ChatGPT event prompts are not enabled. A local writer lease coordinates bridge mutations; it does not control unrelated editors.

## Optional dependencies

Install into the Python environment that launches the companion. From the source root:

```sh
# MCP adapters: Python 3.11+, pinned mcp 2.3.0
python -m pip install -r bridge/requirements-integrations.txt

# Separate optional local agent: Python 3.11+, pinned openai 3.37.0
python -m pip install -r bridge/requirements-agent.txt

# Browser actions
python -m pip install playwright
python -m playwright install chromium
```

Inside a standalone companion ZIP, requirements files are in this companion folder; use their local paths. Skills alone need no MCP dependency. The built-in skill is `web-bridge-project-work`; additional folders and adapters are explicitly selected locally. Adapter tools are allowlisted/schema-validated and never automatically retried after ambiguous interruption. No arbitrary desktop GUI control is automatic.

The local agent requires a model, API-key environment-variable **name**, budgets and explicit local Start. Set the variable before launching the companion. Save/enable alone makes no API call; API usage is separately billed and budgets do not guarantee fixed cost. Required approvals still apply.

Optional browser actions stay within approved origins; browser/HTTP cookies are separate, and downloads, WebSockets and service workers are blocked.

## Verify the connection

Select your own Site-generated plugin and call `bridge_status`, then perform an authorized known-file read or harmless command and inspect the returned evidence. Installing a plugin is not proof of a connected companion. Local artifacts do not automatically update a deployed Site/plugin.

In a full source package see [Setup](../SETUP.md), [Usage](../docs/usage.md), [Troubleshooting](../docs/troubleshooting.md), [Architecture](../ARCHITECTURE.md) and [Security](../SECURITY.md). These surrounding guides are not part of a standalone companion ZIP.
