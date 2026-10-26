# Web-Bridge

**Connect ChatGPT to your project, with permissions controlled on your computer.**

Version **3.2.0** · Setup plugin **1.2.0** · Created by [admin12121](https://github.com/Admin12121) · [MIT license](LICENSE)

Read and update files, run approved host or Docker commands, connect selected skills/MCP applications, and save work for later continuation. A private Site forwards authenticated calls to the local Python companion. The local control panel selects the project and grants access.

![System architecture](images/01-system-architecture.png)

## Start

1. Install Python **3.10+** and [cloudflared](https://developers.cloudflare.com/tunnel/downloads/). Docker is needed only for Docker commands. Node.js **22.13+** is needed for source builds.
2. Provision your own private Site using the trusted setup-plugin ZIP in a Sites-enabled chat with build tools. Explicitly invoke its setup workflow to deploy a private Site and return its generated plugin. Importing the ZIP alone does not deploy anything. The executable [setup skill](plugin/skills/setup-web-bridge/SKILL.md) contains the provisioning instructions.
3. Run the companion:

   ```powershell
   # Windows
   python .\Web-Bridge.pyz
   ```

   ```sh
   # macOS / Linux
   python3 Web-Bridge.pyz
   ```

4. Open the printed local panel and enter its control code. Select your project, permissions, command environment, shell and timeouts. Host commands always need exact approval for each command.
5. Save the printed remote HTTPS endpoint/key only in your private Site's connection form. Select its generated plugin in ChatGPT and call `bridge_status`.
6. Read a known file and submit a harmless command. Inspect its actual result and intended effect before relying on the connection.

Core features need no pip installation or extraction. Keep the companion running. The bundle starts a Quick Tunnel by default; `--local-only` disables it. From the repository root, the source launcher is `python scripts/run.py --tunnel`. Never tunnel the loopback control panel.

![Build, deploy and connect](images/06-build-deploy-connect.png)

## Project files and commands

Use the current `workspace_id` from `bridge_status`. File paths are relative to the selected project. Read the current hash before editing an existing file; omit the hash only when creating an absent file. Approved text creation can create missing parent folders. Folder operations support mkdir, move, recoverable delete and restore. Recursive deletion needs its separate local grant and preview. A proposal is not an applied change: inspect results and read back the file.

![Workspace edit lifecycle](images/04-workspace-edit-lifecycle.png)

For terminal syntax, send `command` with the locally configured `shell`; for exact executable arguments, send `argv`. Never send both. On Windows, use Command Prompt (`cmd`) for npm/npx batch launchers. Omit `environment` to use the local profile; a conflicting explicit environment is rejected.

```json
{"workspace_id":"<current-id>","command":"npm test","shell":"cmd","idempotency_key":"project-tests-001"}
```

Submit once, retain the returned job ID, then poll `command_status`. `pending` and `approved` do not mean execution succeeded. Nonzero exits report `failed` and `success: false`; timeout and cancellation are distinct. Inspect `success`, `exit_code`, output and `cleanup_pending`, then verify the intended effect. `output_offset` reads incremental output.

![Host command lifecycle](images/02-host-command-lifecycle.png)

Command receipts persist locally across restarts and never automatically replay work. Potentially unfinished commands become interrupted with an unknown outcome. Inspect the recorded identity and real project effects; stop or verify the work locally, then choose **I checked this command is stopped**. New writes stay blocked until review. Failed live-Docker cleanup retains its execution identity and writer lease, including when receipt storage is unavailable.

## Docker

Start Docker Desktop in Linux-container mode or a local Linux Docker engine. Choose one of two modes:

| Mode | Behavior |
| --- | --- |
| Isolated snapshot (`container`) | Fresh filtered project copy at `/workspace`; eligible edits/deletions become proposals. The original project is not mounted. |
| Live project (`docker`) | Persistent container with the selected real project mapped into it; commands change shared files directly. |

For a live project, save the selected project first. In **Live Docker project**, set a local context, image, container path such as `/workspace`, and network setting. Choose **Check Docker**, explicitly **Prepare image** if missing, then **Create project container** or **Attach selected container**. An attached container must already have the matching host-project bind mount. Save the live-Docker command profile with `sh` or `bash`, call `docker_status`, and verify a harmless command.

The bridge pins the context and mapping, rejects socket exposure and never silently switches to the host. Stop/remove controls apply only to bridge-owned containers; cancellation targets the command's execution group. Dependencies and changes can persist in a live project.

For snapshots, explicitly prepare and select a supported image: `python:3.12-alpine`, `node:24-alpine` or `alpine:3.21`. No command silently pulls an image. Networking needs a separate grant. Inspect all synchronization results: excluded, unsupported, conflicting or excessive changes retain an artifact rather than proving complete sync. Review it before **Discard retained snapshot**.

![Docker snapshot lifecycle](images/03-docker-snapshot-job.png)

## Skills, applications and continuation

Enable selected skills/MCP tools locally. Load the built-in `web-bridge-project-work` through `skill_list` / `skill_read`, or select trusted folders containing `SKILL.md`. Skill text does not install dependencies, grant access or expose an application.

MCP adapters and the optional local agent require Python **3.11+**. Install only the features you use into the Python environment that launches the companion:

```sh
python -m pip install -r requirements/integrations.txt
python -m pip install -r requirements/agent.txt
```

Configure application adapters locally with their stdio executable/arguments or Streamable HTTP URL, credentials and explicit allowed tool names. An empty allowlist permits nothing. `mcp_tools` discovers selected tools; `mcp_call` validates arguments and does not automatically retry interrupted calls. Inspect application state before retrying a mutation.

Save substantial work with `task_create`, then checkpoint actual evidence, job IDs, remaining work and handoff using `task_checkpoint`. Read `task_list` / `task_read` on the next prompt. After a session change, choose **Use in ChatGPT** locally to rebind the task. `task_verify` requires real configured checks; manual criteria need explicit local owner review.

```json
{"workspace_id":"<current-id>","intent":"Create and verify a project file","checks":[{"kind":"file","path":"example.txt","contains":"ready"}]}
```

For independent continuation, configure an explicit model, API-key environment-variable **name**, and finite step/time/token budgets in the local runner panel, then explicitly start a saved task. Set the key before starting the companion. Saving setup alone makes no API call. API usage is separately billed, approvals still apply, and a budget is not a dollar guarantee.

**Automatic ChatGPT prompts are not enabled** (`chatgpt_events: false`). A skill cannot extend platform session limits. ChatGPT resumes on the next prompt; the independent local runner can continue only after its explicit start.

![Expanded workflow concept](images/07-expanded-workflow-concept.png)

## Tool reference

| Area | Tools |
| --- | --- |
| Connection | `bridge_status` |
| Project | `workspace_list`, `workspace_read`, `workspace_search`, `workspace_edit`, `workspace_operation` |
| Commands | `command_request`, `command_status`, `command_cancel`, `docker_status` |
| Integrations | `skill_list`, `skill_read`, `mcp_tools`, `mcp_call` |
| Saved work | `task_create`, `task_list`, `task_read`, `task_checkpoint`, `task_verify` |
| Web | `list_targets`, `http_request`, `http_batch`, `inspect_html`, `browser_action`, `session_cookies`, `request_history`, `reset_session` |

The machine-readable tool catalog is `src/web_bridge/BRIDGE_TOOLS.json`. Local controls configure permissions, integrations, Docker and the runner; tools cannot grant themselves access.

![Approved HTTP request lifecycle](images/05-approved-http-request.png)

## Limits, recovery and troubleshooting

| Item | Limit or behavior |
| --- | --- |
| Commands | Default 600 seconds; owner-selected maximum up to 3,600 seconds; 30 active jobs |
| Output/history | 64,000 output bytes; 200 compact dashboard rows; newest 160 detailed durable receipts |
| Files/snapshots | 256,000-byte UTF-8 text files; snapshot 50 MB/5,000 entries; ten retained snapshots |
| File protection | Hash checks, path boundaries, recoverable trash; preserve reported recovery paths until reviewed |
| Host/live Docker | Approved commands can change more than file-tool permissions allow; host jobs use the OS account |
| Web | Exact approved origins; no redirects; browser actions need optional Playwright/Chromium |

- **Approved but no effect:** inspect the job's output, exit code, selected environment and intended file/service. Approval permits launch; snapshot changes may still need application. A process exit does not prove a GUI opened.
- **Docker unavailable:** check the local Linux engine, selected context, prepared image, matching mount and shell. Choose the correct local profile instead of falling back to host execution.
- **Writes blocked:** inspect pending approvals, competing writer leases and interrupted-command recovery. Do not replay an uncertain mutation.
- **New tools absent:** rebuild/redeploy the private Site gateway and update its generated plugin; replacing local files alone does not publish the installed deployment.
- **Browser setup:** install `playwright` and run `python -m playwright install chromium` in the companion's environment if using browser tools.

Use `python scripts/run.py --help` for source-launch options and `--runtime` to intentionally reuse an existing runtime after stopping its old process. When migrating an older source install, explicitly pass its previous runtime path to retain its saved state; no credentials are moved automatically. All companion entry points use the same per-user runtime by default: `%LOCALAPPDATA%/Web-Bridge/runtime` on Windows, `~/Library/Application Support/Web-Bridge/runtime` on macOS, and `$XDG_STATE_HOME/web-bridge` or `~/.local/state/web-bridge` on Linux. Grants reset on restart; credentials, configuration, tasks and receipts remain local. Quick Tunnel URLs may change; update the private Site endpoint and leave its key field blank to retain an unchanged key.

Never publish runtime data, credentials, recovery artifacts or selected project contents. Preserve the private Site's identity, encryption secret and database during upgrades. Use only authorized projects/targets. macOS-specific behavior has not been tested on macOS hardware; optional paid-model and real third-party app actions were not exercised in release verification.

![Expanded architecture concept](images/08-expanded-architecture-concept.png)

The eight supplied illustrations are conceptual. Their embedded names/layouts may differ from the actual tool catalog. They do not imply automatic image building, arbitrary desktop control, unlimited audit retention or automatic ChatGPT continuation.

## Develop and package

Python code lives in `src/web_bridge/`, grouped by feature. The application assembles domain services; feature action facades preserve the existing permission-controlled tool interface. MCP/HTTP transport is separate from the web client and browser behavior. The private Site gateway owns its interface, database schema and migrations under `gateway/`.

```text
src/web_bridge/  app.py, cli.py, resources.py
                workspace/ execution/ integrations/ tasks/
                web/ transport/ security/ ui/ skills/
gateway/        Site runtime, interface, database and migrations
plugin/         Setup-plugin metadata and functional skill
scripts/        Source entry, build and release operations
tests/          Python and gateway/control-panel tests
requirements/   Optional integration and agent dependencies
images/         The eight supplied README illustrations
dist/           Generated gateway and release packages (ignored)
```

There is one maintained source tree. Companion/setup ZIPs and the single-file launcher are generated into `dist/release/`; extracted distribution copies are not maintained in the checkout. Source and exported source use the same layout.

```sh
npm ci
npm run build
npm run validate
npm test
python -m pip install pytest
python -m pytest -q tests/python
python scripts/package-release.py
```

Use `python3` on macOS/Linux where needed. The gateway is built into `dist/server/`; release packages go to `dist/release/`. `python scripts/export-repository.py` exports sanitized source to a new destination. Images stay in the repository; portable setup packages omit the illustrations to keep the gateway payload small.

This README is the only explanatory Markdown file. `SKILL.md` files are executable workflow instructions required by the skills and setup plugin. Code, tests and tool schemas remain the implementation reference. No separate docs, guides or planning records are maintained.
