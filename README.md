# Localize (Web-Bridge)

**Connect ChatGPT to your project, with permissions controlled on your computer.**

Version **3.2.0** · Setup plugin **1.2.0** · Created by [admin12121](https://github.com/Admin12121) · [MIT license](LICENSE)

Read and update files, run approved host or Docker commands, connect selected skills/MCP applications, and save work for later continuation. A private Site forwards authenticated calls to the local Python companion. The local control panel selects the project and grants access.

![System architecture](images/01-system-architecture.png)

## Install once, then run `localizeit`

**Windows PowerShell:**

```powershell
irm https://github.com/Admin12121/Localize/releases/download/v3.2.0/install.ps1 | iex
```

**macOS / Linux:**

```sh
curl -fsSL https://github.com/Admin12121/Localize/releases/download/v3.2.0/install.sh | sh
```

After installation, open a new terminal once and run from any folder:

```sh
localizeit
```

The installer prepares uv if needed, verifies the GitHub wheel against the release SHA-256 manifest, installs a managed Python environment, checks the installed command and updates your user's command path. No administrator access, repository clone, Node.js, PyPI account or npm account is required. It prints what it is doing and stops on a failed download, checksum or installation. You can [inspect the Windows installer](scripts/install.ps1) or [macOS/Linux installer](scripts/install.sh) before running it. Re-run the installer to repair or replace this version.

`localizeit` opens the local panel and starts the authenticated tunnel. It reuses an installed cloudflared, or downloads the official release into a private user cache and verifies its published SHA-256 before use. Automatic tunnel preparation supports Windows x64, macOS Intel/Apple Silicon, and Linux x64/arm64; other architectures can use an existing supported cloudflared installation. Docker must be installed and running separately only when you choose Docker execution.

Use `localizeit --local-only` for local controls without a tunnel/download. `localizeit --about` and `localizeit --help` also skip tunnel preparation. `localize` remains an optional alias; `web-bridge` is the legacy command with its explicit `--tunnel` behavior. Existing Web-Bridge 3.2 runtime state remains compatible.

For users who already have uv, the direct alternative is:

```sh
uv tool install https://github.com/Admin12121/Localize/releases/download/v3.2.0/localizeit-3.2.0-py3-none-any.whl
localizeit
```

The primary package and command are both **`localizeit`**. Distribution uses [GitHub Releases](https://github.com/Admin12121/Localize/releases/tag/v3.2.0); bare `uvx localizeit` searches PyPI and is not the installation route. Individual release assets have SHA-256 checksums in `SHA256SUMS`. To remove the installed commands later, use `uv tool uninstall localizeit`; saved project configuration remains in your per-user runtime folder.

## Connect to ChatGPT

1. If you already have access to a deployed bridge plugin, install it from ChatGPT **Plugins** and open its Site connection page. Otherwise, download `web-bridge-setup-plugin.zip` from the GitHub release and use it in a Plugin Creator/Sites-enabled chat with build tools to create your own private Site and generated plugin. Follow the [setup skill](Plugin/skills/setup-web-bridge/SKILL.md). Installing a ZIP alone does not deploy or connect the bridge.
2. Install once as above, then start the companion with `localizeit` from any folder. Keep it running while ChatGPT works.
3. Open the printed local panel and enter its control code. Select your project, permissions, command environment, shell and timeouts. Host commands need exact approval for each command.
4. Save the printed remote HTTPS endpoint/key only in your private Site's connection form. The local control panel remains on loopback and must never be tunneled.
5. Select the generated plugin in ChatGPT using `@`. Ask it to call `bridge_status`, read a known project file and submit a harmless command. Inspect the actual result and intended effect before relying on the connection.

The companion launcher and the ChatGPT plugin have separate setup steps. A local command does not create or publish a Site/plugin. The standalone `Web-Bridge.pyz` release remains available for users who prefer to manage Python and cloudflared themselves; see the platform requirements below.

![Build, deploy and connect](images/06-build-deploy-connect.png)

## Platform requirements

| Platform | Installer requirements |
| --- | --- |
| Windows 10/11 | Built-in Windows PowerShell 5.1+ and HTTPS access to GitHub/Astral |
| macOS Intel / Apple Silicon | Built-in `sh` and `curl`, plus HTTPS access to GitHub/Astral |
| Linux x64 / arm64 | `sh`, `curl`, and `sha256sum` or `shasum`, plus HTTPS access to GitHub/Astral |

The installer selects Python **3.12** automatically; you do not need to find a Python script or manage a virtual environment. Install and run as your regular user. Windows ARM requires an existing supported cloudflared installation for tunnel use.

Docker is optional. For Docker execution, start Docker Desktop with Linux containers on Windows/macOS, or a local Docker Engine on Linux. Use your own local Docker context; remote TCP contexts are rejected. The Linux `docker` group effectively grants root-level control; use rootless Docker where it meets your needs.

The standalone `.pyz` is a compatibility option for users who manage Python and cloudflared themselves. It is not needed for the recommended installer/`localizeit` workflow. Runtime state lives in your per-user application-state directory, separately from release downloads.

## Install and share simply

**Already have a shared plugin?** Open ChatGPT's **Plugins**, find it under your workspace or **Shared with me**, open it and install it. Start a new chat, type `@`, select the bridge, and follow its connection prompts. Plugin availability and sharing depend on your account/workspace. See [OpenAI's installation guide](https://learn.chatgpt.com/docs/plugins).

On **each person's computer**:

1. Run the Windows or macOS/Linux installer from **Install once, then run `localizeit`** above.
2. Open a new terminal and run `localizeit`. The standalone `.pyz` alternative is for users who prefer to manage Python/cloudflared themselves.
3. Unlock the printed local panel, select the project and permissions, and choose the command environment. Docker is optional unless you choose Docker execution.
4. In the authorized Site connection page, save **your own** printed remote endpoint and connection key. Keep the companion running.
5. In a new ChatGPT chat, select the installed bridge with `@` and send:

   ```text
   Use this bridge. First call bridge_status and show my selected project,
   environment and permissions. Then list the files in my project.
   Inspect actual tool results before saying an action completed.
   ```

**Sharing an existing deployment:** use the plugin's sharing settings for the intended people/workspace, and ensure its Site is also accessible to them. Send the supported plugin link, the GitHub release link and the sample prompt above. Each recipient installs the plugin and connects their own companion; sharing a plugin does not install local software or grant access to your PC. Sharing requires the applicable workspace permission. [OpenAI's sharing guide](https://learn.chatgpt.com/docs/build-plugins#share-the-plugin-with-your-team)

**Sharing independent copies:** send `web-bridge-setup-plugin.zip` and the Localize wheel (or `Web-Bridge.pyz`). Each recipient uses the setup workflow to provision their own account-owned private Site/plugin once, then follows the steps above. Initial provisioning requires Sites/build capabilities; ordinary chat can use the connected plugin afterward. Share release assets, not your runtime folder, credentials or connection key.

Build assets are in `dist/release/` after `npm run build`; `python scripts/package-release.py` also produces the combined release ZIP. Local packaging does not publish a Site or create a public one-click installation link.

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

MCP adapters and the optional local agent require Python **3.11+**. For the GitHub launcher, request the extras in the same isolated environment:

```sh
uvx --python 3.12 --from "localizeit[integrations,agent] @ https://github.com/Admin12121/Localize/releases/download/v3.2.0/localizeit-3.2.0-py3-none-any.whl" localizeit
```

Use only `integrations` or `agent` inside the brackets if you need one feature. For a persistent installation, use `uv tool install --python 3.12 --force` followed by that same quoted package URL. Installing extras does not grant access or start a paid model call. For source or standalone `.pyz` runs, install `requirements/integrations.txt` and/or `requirements/agent.txt` with pip into the Python environment that launches the companion.

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
                web/ transport/ security/ setup/ ui/ skills/
gateway/        Site runtime, interface, database and migrations
Plugin/         Setup-plugin metadata and functional skill
scripts/        Source entry, build and release operations
tests/          Python and gateway/control-panel tests
requirements/   Optional integration and agent dependencies
images/         The eight supplied README illustrations
dist/           Generated gateway and release packages (ignored)
```

There is one maintained source tree. Companion/setup ZIPs and the single-file launcher are generated into `dist/release/`; extracted distribution copies are not maintained in the checkout. Source and exported source use the same layout.

Run directly from a source checkout without a global installation:

```sh
uvx --from . localizeit
```

To build and verify the gateway and release packages, use Node.js **22.13+** and Python **3.12**. The GitHub Actions themselves use Node 24; their runtime is separate from the Node version selected for project commands.

```sh
npm ci
npm run build
npm run validate
npm test
python -m pip install pytest build uv -r requirements/integrations.txt -r requirements/agent.txt
python -m pytest -q tests/python
python -m build --wheel --outdir dist/release
python scripts/package-release.py
```

Use `python3` on macOS/Linux where needed. The gateway is built into `dist/server/`; release packages go to `dist/release/`. `python scripts/export-repository.py` exports sanitized source to a new destination. Images stay in the repository; portable setup packages omit the illustrations to keep the gateway payload small.

This README is the only explanatory Markdown file. `SKILL.md` files are executable workflow instructions required by the skills and setup plugin. Code, tests and tool schemas remain the implementation reference. No separate docs, guides or planning records are maintained.
