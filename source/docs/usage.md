# Usage and tool reference

[Documentation index](index.md) · [Troubleshooting](troubleshooting.md)

This page describes the implemented **3.1.1** tools. Their authoritative schemas are in [`bridge/BRIDGE_TOOLS.json`](../bridge/BRIDGE_TOOLS.json). JSON below represents the arguments to the named tool, not a shell command.

## Start with local configuration

Open the companion panel using the address/control code printed in its terminal. Select one project folder and grant read, write, command, network and host permissions as needed. The Site cannot grant these permissions. Do not tunnel the control panel.

Call `bridge_status`. Check `paused`, `workspace`, `workspace_id` and `permissions`. `docker_cli_available` means the executable was found; it does not prove the engine or image is ready. Use the current returned workspace ID in all workspace operations and command submissions. A configuration change or pause invalidates older IDs and pending grants.

## List, read and search

Call `workspace_list`:

```json
{"workspace_id":"<current-workspace-id>","path":""}
```

Call `workspace_read` for a returned text file:

```json
{"workspace_id":"<current-workspace-id>","path":"README.md"}
```

Save its `sha256` before editing. Call `workspace_search` with a literal query and optional folder path. Paths are relative with forward slashes. Absolute paths, traversal, symlinks/junctions, private paths and selected sensitive patterns are rejected.

## Edit or create a text file

Call `workspace_edit` for an existing file using the exact hash from `workspace_read`:

```json
{"workspace_id":"<current-workspace-id>","path":"README.md","expected_sha256":"<hash-from-read>","text":"Updated content\n"}
```

The response normally contains an `edit_id`, diff, and `approval_required: true`. Review and approve the edit in the local panel. A proposal does not mean the original file changed. With the local session-write option enabled, the response also contains the apply result. Read back the file to verify its contents and hash.

To create an absent text file, omit `expected_sha256`; its parent directory must already exist. Version 3.1.1 cannot create directories, move/rename files, delete files/folders, or edit arbitrary binary content through workspace tools. Concurrently modified files are rejected rather than silently overwritten.

## Run a host command

Enable command requests and host mode locally. Call `command_request` once:

```json
{"workspace_id":"<current-workspace-id>","environment":"host","argv":["python","-c","print('bridge-command-check')"],"cwd":"","timeout_seconds":30,"idempotency_key":"host-check-0001"}
```

`argv` is an executable and its individual arguments. It is not a shell command string. The executable must exist on the host. Windows `.cmd`/`.bat` programs require an explicit, locally approved `cmd.exe` invocation. Commands receive a minimal environment, so variables or virtual environments from another terminal may not be present.

The command starts as `pending`. Approve its exact arguments in the local panel, then call `command_status`:

```json
{"job_id":"<returned-job-id>"}
```

Poll that job instead of submitting it again. `approved` means queued to start; `running` means the process was launched. A terminal result includes `exit_code` when a process exited. **Known issue: `completed` does not imply exit code 0 in this version.** Confirm exit code, output and the requested effect before reporting success. A CLI exit does not prove a window opened or a background service is healthy.

An identical retry may reuse the same idempotency key. A changed command or policy needs a new key. Use `command_cancel` with the job ID to request cancellation. Cancellation attempts to terminate the owned process group/container; separately managed services need their own lifecycle checks.

Host execution uses your OS-account privileges. `cwd` determines the working directory, not which files the command can access. Each host command needs individual approval.

## Run a Docker snapshot command

Start a local Linux Docker engine. Prepare one of `python:3.12-alpine`, `node:24-alpine` or `alpine:3.21` yourself. Select that image and enable command requests in the local panel. For `node:24-alpine`, call:

```json
{"workspace_id":"<current-workspace-id>","environment":"container","argv":["node","-e","console.log('container-command-check')"],"cwd":"","timeout_seconds":30,"idempotency_key":"container-check-0001"}
```

Container mode is the current default if `environment` is omitted. It is not selected automatically from a persistent host/Docker project profile. The bridge checks Docker context, Linux engine and selected image; it never downloads an image or switches to host execution as a fallback.

Each command receives a fresh filtered copy of the project at `/workspace`. The container root filesystem is read-only; this staged project mount is writable. Sensitive files, Git data and dependency folders are excluded. Networking is disabled unless granted locally. Image contents persist, but changes in the temporary container root do not become a reusable development environment.

When write permission is enabled, eligible text changes become proposals for the original project. Apply them locally or enable session writes. Check each `changes` result: conflicts, limits and unsupported changes can prevent application. Deleted snapshot files are not deleted in the host project. New nested directories are not created automatically. The temporary copy is removed afterward. There is no connection to an existing container, persistent development container, or full project synchronization in 3.1.1.

## Approved web targets and optional browser

Add named website origins in the local panel, and separately allow private lab targets when required. Call `list_targets` to discover permitted names. `http_request` and `http_batch` use those names with bounded relative paths. `inspect_html`, `session_cookies`, `reset_session` and `request_history` expose bounded inspection/session evidence. Redirects are not followed.

`browser_action` requires local Playwright/Chromium and follows its own approved-origin restrictions. HTTP/browser cookies are separate. Browser tools do not provide general desktop application control.

## Current limits and persistence

| Item | Limit/behavior |
| --- | --- |
| Text file | 256,000 bytes; UTF-8 only |
| Directory listing | Up to 500 entries |
| Workspace walk/snapshot | Up to 5,000 entries; snapshot up to 50,000,000 bytes |
| Search | Up to 50 matching lines |
| Pending edits | Up to 20; approval expires after 300 seconds |
| Command | 1–120 seconds; up to 50 argument strings |
| Command output | Up to 64,000 bytes, combined stdout/stderr |
| Job history | Up to 30 submitted jobs per companion session |
| Snapshot reconciliation | Up to 20 eligible changed files; deletions not applied |
| Grants, proposals, jobs | In memory; reconfigure/restart requires fresh permissions |

Connection credentials persist in the runtime directory, separately from session permissions. The current bridge has no durable task checkpoints, autonomous local agent, upstream MCP client, or local skill discovery tools. See [proposed upgrades](roadmap.md).
