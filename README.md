# Web-Bridge

**Connect ChatGPT to your project, with permissions controlled on your computer.**

Version **3.2.0** · Created by [admin12121](https://github.com/Admin12121) · [MIT license](LICENSE)

Web-Bridge combines your private ChatGPT Site, an MCP gateway, and a local Python companion. Read and update project files, run approved commands, use a persistent Docker project, connect selected skill/MCP adapters, and save work to resume later.

## Start here

1. Deploy your own private Site with the trusted setup package. Follow [Setup](source/SETUP.md); importing the package alone does not deploy it.
2. Install **Python 3.10+** and [cloudflared](https://developers.cloudflare.com/tunnel/downloads/), then download `Web-Bridge.pyz` from your trusted release or private Site.
3. Run the companion:

   ```powershell
   # Windows
   python .\Web-Bridge.pyz
   ```

   ```sh
   # macOS / Linux
   python3 Web-Bridge.pyz
   ```

4. Open the printed local panel, enter its control code, select your project, and save the permissions and command profile you want.
5. Save the printed remote Site endpoint and connection key **only in your private Site's connection form**. Select its generated plugin in ChatGPT.
6. Call `bridge_status`, check the workspace and profile, then read a known file or run a harmless command and inspect its actual result.

Core companion features need no pip installation or extraction. The bundle starts a Quick Tunnel by default; use `--local-only` to disable it. Keep it running while connected. Docker, browser actions, MCP adapters and the optional local agent have separate setup requirements.

## How the connection works

![ChatGPT, private Site and local companion](docs/images/01-system-architecture.png)

```text
ChatGPT + your Site-generated plugin
    → private Site / authenticated MCP gateway
    → authenticated HTTPS tunnel
    → local Python companion
        ├─ selected project files and saved tasks
        ├─ approved HTTP/browser targets and selected MCP adapters
        └─ approved host, snapshot or live Docker command jobs

Separate local panel: project, permissions, approvals, Docker setup, pause
```

The companion enforces permissions. The Site cannot select a project, grant access or approve a command. Only the authenticated RPC endpoint belongs behind the tunnel; the local control panel stays on loopback. The illustration is conceptual: host commands use your OS account and are not confined to the selected project.

## What 3.2 provides

| Area | Available behavior | Boundary |
| --- | --- | --- |
| Project files | List/search/read, hash-checked text edits and nested creates; mkdir, move, recoverable delete and restore | Bounded UTF-8 edits; local approval or separate session grants; recursive deletion needs its own grant |
| Commands | Explicit shell text or exact argument arrays; launch evidence, success/failure, timeout/cancellation, incremental output | Host always needs approval for each command; process success still needs an outcome check |
| Docker | Filtered snapshot jobs, or a persistent container mapped to the real project; local check/pull/create/attach controls | Explicit local setup; live commands can change shared files directly; no host fallback |
| Skills and applications | Built-in project-work skill, selected local skill folders and allowlisted stdio/HTTP MCP tools | Optional dependencies; adapters define available application access; no automatic arbitrary desktop control |
| Saved work | SQLite tasks, evidence, checkpoints, handoff and machine checks; resume with ChatGPT | Resume on the next prompt; automatic ChatGPT event prompts are not enabled |
| Optional local agent | Explicitly started API-backed saved-task execution within step/time/token budgets | Separate API credentials/dependencies and billing; approvals still apply; no fixed-cost guarantee |
| Web work | Approved-origin HTTP, forms, cookies/history and optional Chromium actions | Exact locally approved origins; no redirects; separate browser setup |

Command profiles default to **10 minutes** and allow an owner-selected maximum of **1 hour**. Output is bounded to 64,000 bytes. The dashboard retains up to 200 compact rows and the newest 160 detailed receipts; durable identity/idempotency receipts remain across restarts. Text files are limited to 256,000 bytes; snapshots to 50 MB and 5,000 entries. See [usage and limits](source/docs/usage.md).

## Commands: approve, poll, verify

![Command approval, execution and result polling](docs/images/02-host-command-lifecycle.png)

Use `command_request` once with an idempotency key, then poll `command_status` using the returned job ID. A nonzero exit now reports `failed` and `success: false`; timeout and cancellation have distinct states. Check `success`, `exit_code`, output and `cleanup_pending`, then verify the intended file or service. Approval only permits launch.

For terminal syntax use `command` with the locally configured `shell`. For exact executable arguments use `argv`; never supply both. On Windows use `command` with `shell: "cmd"` for npm/npx batch launchers. Omit `environment` to use the local profile; a conflicting explicit environment is rejected. [Tool examples](source/docs/usage.md) use the real API names rather than the illustration's labels.

## Choose the right Docker mode

**Isolated snapshot** runs against a filtered temporary project copy. Eligible changes become separately controlled proposals. Unsupported, excluded, conflicting or over-limit changes are reported; affected snapshots remain available locally for inspection rather than disappearing silently.

**Live Docker project** maps the selected real folder into a persistent Linux container. In the local panel, save Docker setup, check the engine, explicitly prepare an image if needed, and create or attach a validated container. Select the live Docker command profile. Dependencies and project changes can persist; commands write directly to shared files. Stop/remove controls apply only to bridge-owned containers. See [Docker setup](source/SETUP.md#docker-modes).

## Save and resume work

Use `task_create`, checkpoint evidence and remaining work with `task_checkpoint`, then inspect `task_list` / `task_read` on the next prompt. After a restart or project-session change, the owner selects **Use in ChatGPT** in Saved work to rebind the task. `task_verify` checks configured file contents/hashes or successful command job IDs before marking it machine-verified complete. Manual/text criteria can instead be explicitly confirmed by the owner in local Saved work; that is recorded as owner review. Interrupted mutations are not automatically replayed.

For independent continuation, install/configure the optional local agent and explicitly start a saved task locally. Its budgets bound each run, not its dollar cost. A skill alone cannot keep ChatGPT running or send a new prompt. This build reports `chatgpt_events: false`.

## Guides

| Guide | Purpose |
| --- | --- |
| [Setup and migration](source/SETUP.md) | Connection, Docker, optional dependencies and upgrading from 3.1 |
| [Usage](source/docs/usage.md) | All 27 tools, examples, approvals and limits |
| [Troubleshooting](source/docs/troubleshooting.md) | Command results, Windows shells, Docker, files and task recovery |
| [Architecture](source/ARCHITECTURE.md) | Source ownership, data flow and boundaries |
| [Companion reference](source/bridge/README.md) | Launch options, runtime storage and local controls |
| [Illustrated workflows](docs/illustrations.md) | Eight preserved diagrams with current implementation notes |
| [Release scope and next steps](source/docs/roadmap.md) | Implemented behavior and remaining limitations |
| [Contributing](source/CONTRIBUTING.md) / [Security](source/SECURITY.md) | Development checks and private reporting |

## Develop and package

Canonical development code is in **`source/`**. Root `Companion/`, `Plugin/` and `Web-Bridge.pyz` are generated distributions. Requires Node.js 22.13+ and Python 3.10+; optional MCP/agent packages require Python 3.11+.

```sh
cd source
npm ci
npm run check:repo
npm run build
npm run validate
npm test
python -m pip install pytest
python -m pytest -q bridge/tests
python scripts/package-release.py
```

Use `python3` on macOS/Linux where needed. Outputs go to `source/dist/` and `source/outputs/`. `python scripts/export-repository.py` exports sanitized source and refuses to overwrite an existing destination. Large repository illustrations stay outside the portable setup payload.

Version 3.2 source and packaged artifacts do not automatically update an already installed private Site/plugin: deployment is a separate step. Preserve an existing deployment's identity and secrets during an upgrade. Never publish runtime state, keys or selected project data. Use only projects and targets you own or are authorized to work on. This project has not been independently security audited.
