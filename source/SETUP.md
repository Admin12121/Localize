# Set up Web-Bridge 3.2

[README](README.md) · [Usage](docs/usage.md) · [Troubleshooting](docs/troubleshooting.md)

Each owner uses their own private Site and companion. All project access, command environment selection and integration grants happen locally.

## Requirements

| Component | When needed |
| --- | --- |
| ChatGPT account/workspace with Sites, plugin creation and build/file tools | Private gateway provisioning; availability depends on the account |
| Python 3.10+ | Core companion and packaging; no core pip dependency |
| [cloudflared](https://developers.cloudflare.com/tunnel/downloads/) | Default remote tunnel |
| Local Linux Docker engine | Snapshot or live Docker commands |
| Playwright + Chromium | Optional browser actions |
| Python 3.11+ and `bridge/requirements-integrations.txt` | Optional MCP adapters (`mcp==2.3.0`) |
| Python 3.11+ and `bridge/requirements-agent.txt` | Optional local API agent (`openai==3.37.0`) |
| Node.js 22.13+ | Source builds/development |

## 1. Provision your private Site

Use the trusted `Web-Bridge-Setup-Plugin.zip` release package in a build-capable Sites chat. Where ZIP import is supported, import it and explicitly invoke **Web-Bridge Setup**: “Deploy my own private Site from this package and return its generated plugin.”

The workflow copies sanitized source, creates an account-owned private Site, configures a fresh encryption secret, builds/publishes it and returns that Site's generated plugin. Import alone does not deploy it. If account capabilities are missing, resolve that setup requirement rather than using another owner's private gateway.

## 2. Start the companion

```powershell
# Windows, downloaded bundle
python .\Web-Bridge.pyz
```

```sh
# macOS / Linux, downloaded bundle
python3 Web-Bridge.pyz
```

No extraction or pip installation is required for core features. The bundle creates a Quick Tunnel by default; add `--local-only` to disable it. From the source root use `python bridge/launch.py --tunnel` instead. Source launches do not tunnel unless requested.

Keep the process running. The terminal prints the local control panel URL/code and the remote Site endpoint/connection key. Enter each only in its intended local or private Site form. Never tunnel the control panel.

## 3. Select the project and command profile

Open the printed loopback panel and unlock it with its local control code. Select a regular local project folder and alias. Enable read/search, and enable writes, commands or integrations only as needed.

Choose the command environment explicitly:

| Profile | Behavior |
| --- | --- |
| This computer (`host`) | OS-account execution; enable host access and approve every exact command |
| Isolated snapshot (`container`) | Fresh filtered Docker copy; eligible changes reconcile through proposals |
| Live Docker project (`docker`) | Persistent mapped real project; configure it below first |

Choose an installed shell: PowerShell/PowerShell 7/Command Prompt on Windows, or `sh`/`bash` as appropriate. Both Docker modes require `sh` or `bash` inside their Linux image. Set default/max timeouts; defaults are 600/3,600 seconds and neither may exceed 3,600.

Text session writes, folder-operation session approval, recursive deletion, and container-command session approval are separate options. The container approval option applies to snapshot and live Docker jobs; host jobs always need individual approval. Live Docker commands directly share files, so text/operation proposal toggles do not constrain what an approved live command writes.

Saving permissions replaces the workspace ID and revokes pending work. Pausing stops current access; it cannot undo changes already made. After restart, grant access again.

## Docker modes

### Isolated snapshot

Start Docker Desktop in Linux-container mode or a local Linux Docker engine. Prepare a supported image locally and select it under Isolated commands:

```sh
docker info --format '{{.OSType}}'
docker pull node:24-alpine
docker image inspect node:24-alpine
```

The engine must report `linux`. Supported snapshot selections are `python:3.12-alpine`, `node:24-alpine` and `alpine:3.21`. Snapshot execution checks the current local context and pins it for the job; it does not silently pull images or fall back to the host.

The original folder is not mounted in snapshot mode. Source exclusions and size limits apply. Inspect every reconciliation result and approve eligible text/operation proposals. Unresolved changes retain a local artifact; review it before using **Discard retained snapshot**. Ten retained snapshots block additional snapshot jobs until inspected/discarded.

### Persistent live Docker project

1. Save the selected project and command permissions first.
2. Under **Live Docker project**, choose a local Docker context, image, container project path (for example `/workspace`) and explicit network setting. Save setup and choose **Check Docker**.
3. If the image is missing, choose **Prepare image** to explicitly download it. No request triggers an automatic pull or build.
4. Choose **Create project container**, or enter an existing container ID/name and choose **Attach selected container**.
5. Existing containers must already map the selected host project to the configured container path. Inspect broader access locally; attachment may need the explicit broader-access acknowledgment. The bridge rejects socket exposure and invalid mappings.
6. Save the **Live Docker project** command profile with `sh` or `bash`. Call `docker_status` and run a harmless check.

The selected context/endpoint and project mapping are pinned and checked. The live mount is the real project, including files excluded from snapshot/file tools; command effects do not wait for edit proposals. Installed dependencies and container state persist. Start/log actions are local; stop/remove are restricted to bridge-owned containers. Removing a managed container keeps host project files. Cancellation targets the command's execution group rather than stopping a shared attached container.

## 4. Connect and verify

Open your private Site connection page and save the printed remote HTTPS endpoint/key. A localhost control URL is not a Site endpoint. Select your Site-generated plugin, then:

1. Call `bridge_status`; verify version, project alias, pause state, permissions and command profile.
2. Read a known small text file with its current `workspace_id`.
3. Submit a harmless [command example](docs/usage.md), approve if required, and poll its returned job ID.
4. Confirm `success`, `exit_code`, output and the intended effect. A failed command is now `failed`; timeout and cancellation are separate.
5. If testing a write, inspect its apply result and read back the real project. A snapshot process exit alone does not prove all changes synchronized.

## 5. Optional selected skills and MCP applications

Enable **Allow selected skills and MCP tools** locally. The built-in `web-bridge-project-work` skill is available through `skill_list` / `skill_read`. Add additional trusted folders containing `SKILL.md`; resources stay scoped to each selected folder.

For MCP, install the optional package into the same Python environment that launches the companion, using Python 3.11+:

```sh
python -m pip install -r bridge/requirements-integrations.txt
```

Add an application adapter locally: name, stdio executable/arguments or Streamable HTTP URL, explicit allowed tool names, and timeout. An empty tool allowlist permits no tools. Supply credentials only in the local environment/header fields. `mcp_tools` discovers selected tools; `mcp_call` validates their schemas and does not automatically retry interrupted calls. A skill does not install an app or adapter; no general desktop GUI control is enabled automatically.

## 6. Save work and optionally start a local agent

Create a task with acceptance checks and checkpoint evidence/handoff. ChatGPT can resume it on the next prompt via `task_list` / `task_read`. After a session change, select **Use in ChatGPT** in the local Saved work panel to rebind it. Manual/text acceptance criteria do not machine-verify automatically; after personally reviewing results the owner can use **Confirm reviewed complete** locally, which records owner review. Automatic ChatGPT event prompts are not enabled in this build.

For independent API-backed continuation, install the separate optional dependency using Python 3.11+:

```sh
python -m pip install -r bridge/requirements-agent.txt
```

Set the API key in an environment variable **before launching the companion**. In Optional local agent, enter only the variable's name (such as `OPENAI_API_KEY`), select an explicit available model, and save step/time/token limits. Save/enable alone makes no API call. Explicitly start a saved task locally; API usage is separately billed and budgets do not guarantee a fixed dollar cost. Approvals and writer leases still apply. Cancel locally when needed.

## Upgrade from 3.1

Stop the old companion, replace its bundle and restart. To reuse an older source installation's runtime/key intentionally, pass `--runtime .runtime` from that old installation folder. Do not run two companions against the same runtime.

Permissions reset: reselect the project and explicitly save the environment/shell/timeouts and separate text, operation, recursive-delete and container grants. Do not assume the old implicit Docker behavior. Use the new `workspace_id`; resume/rebind saved work through local controls. Job history is session state and old running jobs are not resumed.

Quick Tunnel URLs can change; update the private Site endpoint. Leave its key field blank to retain an unchanged saved key. Preserve the existing private Site identity, encryption secret and database when upgrading it. Rebuild/redeploy its gateway and regenerate/update its plugin to expose the new tool catalog; replacing a local bundle does not publish that deployment.

Use sanitized source/release outputs for distribution, never runtime folders or selected project contents. See [Contributing](CONTRIBUTING.md) for checks and packaging.
