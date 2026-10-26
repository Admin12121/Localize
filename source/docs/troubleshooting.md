# Troubleshoot Web-Bridge 3.2

[Documentation index](index.md) · [Setup](../SETUP.md) · [Usage](usage.md)

## A command was approved but nothing happened

Read the existing job with `command_status`; do not submit it again. Inspect its exact command/argv, environment, shell, relative working directory, launch evidence, state, `success`, exit code, output and snapshot changes. Keep credentials and private source out of shared diagnostics.

| Result | Next action |
| --- | --- |
| `pending` | Approve locally; nothing ran yet |
| `approved` | Wait/poll; launch is queued |
| `running` | Read incremental output; wait or cancel |
| `completed`, `success: true`, exit 0 | Verify the requested file, server or app state |
| `failed` | Inspect exit/error/output; nonzero exits are failures in 3.2 |
| `timed_out` | Check profile/request timeout and whether cleanup is pending |
| `cancelled` | Check local cancellation, pause or policy changes; wait for cleanup |
| `denied` / `expired` | No valid approval to launch; resolve locally |

The old 3.1 outcome-label defect is fixed: an exit of 7 is `failed` with `success: false`. A transport response or approval still does not establish success. A successful CLI exit does not establish a GUI window or healthy background service.

Use `output_offset` with the previous `next_output_offset` for incremental text. `truncated` means bounded output is incomplete. `cleanup_pending: true` means process cleanup has not settled even though cancellation/timeout is visible. Wait before competing writes. Services started outside the bridge's process ownership require separate lifecycle checks.

## Wrong environment or shell

The command profile is chosen locally. Omitting `environment` follows it; a conflicting explicit environment is rejected. Read `bridge_status` after permission saves rather than assuming host or Docker. `cwd` is relative to the selected project and is not a filesystem security boundary.

Use `command` plus the installed shell for pipes, redirects, built-ins and ordinary terminal syntax. Use `argv` only for an exact native executable and separate arguments; never supply both. A whole command line is not an executable name.

On Windows, npm/npx often resolve to batch launchers. Exact-argv mode rejects `.cmd`/`.bat`; use `command: "npm --version"` with `shell: "cmd"` and a compatible locally selected profile. PowerShell cmdlets require PowerShell. If PowerShell execution policy blocks a script, report that policy error and select an intended local shell rather than silently bypassing policy. Host commands receive a minimal environment; another terminal's activated environment or credentials may be missing.

## Docker commands

### Engine or context is unavailable

Start Docker Desktop with Linux containers or your local Linux engine. In local controls choose **Check Docker** for live projects. Verify locally if necessary:

```sh
docker context show
docker info --format '{{.OSType}}'
```

The engine must report `linux` and use a supported local socket/named pipe. A stopped engine or access-denied pipe is different from a missing CLI. Live setup pins its selected context/endpoint; if it changes, reconfigure locally. Snapshot readiness resolves the local context and pins it for that job. The bridge does not switch to host execution on failure.

### Image missing

Snapshot mode needs one supported image already prepared locally: `python:3.12-alpine`, `node:24-alpine` or `alpine:3.21`. Pull it yourself and select the same one. For live Docker, save its chosen image and explicitly choose **Prepare image**. A remote command never silently pulls/builds an image.

### Existing container cannot attach

Save the project and live Docker setup first. The selected running/container configuration must map that exact real host project to the configured container path. Inspect mounts and privileges locally. Socket exposure, invalid mappings and other disallowed access are rejected; some broader configurations need an explicit owner acknowledgment. Use a compatible Linux image with `sh`, `setsid` and the standard utilities required by command supervision. Stop/remove controls apply only to bridge-owned containers, not arbitrary attached environments.

### Dependencies or changes disappear

Check the mode. A snapshot is a fresh filtered copy with dependencies/Git/sensitive paths excluded, read-only container root and optional networking. It is not a reusable development environment. Use an intentionally configured live project for persistent dependencies/shared files. Live Docker modifies the real project directly; those effects do not wait for proposal approval.

### Command succeeded but original files differ

For snapshots, inspect every `changes` entry and apply eligible proposals locally. Text edits and delete operations have distinct grants. Unsupported/excluded changes, conflicts, limits and disabled synchronization can leave differences. A retained `snapshot` artifact is evidence of unresolved work, not proof of complete sync. Inspect it locally before choosing **Discard retained snapshot**. At ten retained snapshots, review/discard before another snapshot job.

For live Docker, verify the actual selected mount and path. Cancellation targets the per-command execution group; it does not intentionally stop unrelated work in the attached container. A cancelled command may already have changed shared files.

## Workspace operation rejected

Use the latest workspace ID and relative forward-slash paths. Select a regular local project folder rather than a drive root, home, link or runtime folder. Sensitive/excluded files, links, over-limit files and binary text edits are rejected.

Read the current hash before overwriting, moving or deleting a file. A mismatch means another change won: inspect it before proposing again. Missing parents can be created with an approved absent-file edit or `mkdir`; destination conflicts are not overwritten. Nonempty-folder deletion needs a separate recursive grant and bounded preview.

Deletion returns a recovery ID; restore with `workspace_operation` after ensuring the destination is appropriate and absent. Preserve excluded project trash and its runtime records until recovery is no longer needed. If a write returns `recovery_path`, inspect it locally: POSIX original-inode backups intentionally remain available for possible writes through pre-existing open descriptors. Do not retry an overwrite blindly or delete recovery content as part of automated cleanup.

## Permissions or old jobs disappeared

Permission changes invalidate workspace IDs and pending approvals, cancel current jobs and clear proposals. Pausing revokes access without undoing completed writes. Restart requires new grants. Command receipts persist in SQLite: unfinished executions become interrupted, never automatically replayed. Inspect the recorded command/process/container identity and actual project effects in local command history. If recovery is required, stop or otherwise verify the old work locally, then choose **I checked this command is stopped**. Until that explicit review, new writes in the affected project are blocked. A cleanup error in the current session also produces an interrupted, unknown outcome: the owned Docker execution identity and writer lease are retained until local review, even if receipt storage is unavailable. The dashboard keeps 200 compact rows and the newest 160 detailed receipts; older identity/idempotency tombstones can have no output. At most 30 commands may be active; wait/cancel rather than restarting to bypass the limit.

Tasks persist independently. Rebind a saved task with **Use in ChatGPT**, inspect its handoff and verify actual effects. Do not replay an old mutation merely because a response or session ended. A command check pointing to a previous session's missing job cannot prove current success.

## Skills or application tools are absent

Enable integrations and explicitly add trusted skill folders or MCP adapters locally. The built-in skill name is `web-bridge-project-work`; a custom skill needs a readable `SKILL.md`. Skill text does not install an application or expose its tools.

MCP adapters need Python 3.11+ and the optional requirements in the **same environment that starts the companion**. Check adapter executable/arguments or HTTP endpoint, credentials and explicit allowed tool names. An empty allowlist exposes nothing. Adapter schemas are validated; calls are not automatically retried because interrupted mutations may already have occurred. Inspect the application state before retrying. Credentials stay in local configuration; do not paste them into chat.

## Saved work will not continue

ChatGPT resumes on the next prompt; this build does not enable automatic event prompts (`chatgpt_events: false`). Read `task_list` / `task_read`, then locally choose **Use in ChatGPT** if the workspace session changed. A task marked partial/blocked/awaiting approval has not completed. `task_verify` requires real supported checks; empty or manual-only checks do not automatically pass. Refine checks with `task_checkpoint` plus the latest revision while preserving requirements, or personally inspect the outcome and use **Confirm reviewed complete** locally; this records owner review, not machine verification.

For the optional local agent, install its separate Python 3.11+ dependency, set the API key environment variable before launch, enter its **name**, choose an explicit model, save budgets and explicitly start the saved task. Saving/enabling alone does not call the API. Inspect budget exhaustion, pending approvals and runner evidence. API calls are separately billed; token/time/step limits are not a dollar guarantee. Another bridge writer lease can require waiting; do not run competing mutation clients.

## Site cannot connect or new tools are missing

Keep the companion/tunnel running. Use the current printed remote HTTPS `/mcp` endpoint, not the loopback control URL or an old Quick Tunnel. Save keys only in your private Site; leave the key field blank to retain an unchanged saved key when updating its endpoint.

Check the selected Site-generated plugin and gateway version. Replacing local source/bundles does not publish an already installed Site or refresh its tool catalog. Upgrade that deployment separately while preserving identity, encryption secret, database and sharing. Never expose the local control listener as a connection workaround.

## Development checks do not start

Run from the canonical source root with Node.js 22.13+ and Python 3.10+. Install pytest separately. Build before worker tests because they read `dist/server/index.js`. Optional MCP/agent packages need Python 3.11+; real Docker/browser checks need their respective local installations. Record skipped optional paths accurately; never make paid API calls just to claim routine verification.
