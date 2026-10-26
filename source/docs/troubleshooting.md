# Troubleshooting Web-Bridge 3.1.1

[Documentation index](index.md) · [Setup](../SETUP.md) · [Usage](usage.md)

## A command says completed but nothing happened

Open the exact job in the local panel, or call `command_status` with its job ID. Keep the environment, argument array, relative working directory, state, exit code, output and snapshot/change results together when investigating. Do not share connection keys or local control codes.

| Observed result | Meaning and next check |
| --- | --- |
| `pending` | No execution yet; review the exact command in local approvals |
| `approved` | Approved and queued; poll until launch or a terminal result |
| `running` | The process launched; inspect output and wait or cancel |
| `completed`, exit code 0 | Process exited successfully; verify its intended file/service/window separately |
| `completed`, nonzero exit code | Command failed despite the current misleading state label; inspect its output |
| `failed` | Launch/execution raised an error; check executable, working directory, permissions and Docker |
| `cancelled` | Cancellation, timeout, pause or policy revocation may have stopped the operation; the current state does not distinguish all reasons |
| `denied` / `expired` | The pending command did not receive valid permission to run |

**Confirmed defect:** the current runner assigns `completed` after a process exits without checking whether its exit code is zero. A temporary-fixture diagnostic reproduced `completed` with exit code 7. This is recorded for repair, not fixed by these docs. It does not establish the cause of every no-effect command.

Also check:

- **Wrong environment:** omitting `environment` currently chooses a Docker snapshot, not the host. A result in that temporary copy is not automatically a host change.
- **Wrong working directory:** `cwd` is relative to the selected project. An empty value means its root. Files may have been written somewhere other than expected by the program.
- **Missing application/environment:** host execution receives a minimal environment. A terminal's active virtual environment, credentials or custom variables may not be present.
- **Shell assumptions:** an argument array does not expand pipes, redirection or shell built-ins. Use an explicit shell only when its exact invocation is intended and approved. Windows batch wrappers need explicit `cmd.exe` invocation.
- **Unapplied changes:** Docker results can be pending proposals or conflicts. Inspect every change; deletions and new nested directories do not sync today.
- **GUI assumptions:** a successful CLI exit does not prove an interactive window appeared. Check application state separately.

Do not repeatedly resubmit a pending or ambiguous command. Poll its existing job ID; resubmitting can duplicate effects.

## Verified Windows command-launch behavior

A disposable-project check using the actual runner found that Python, Node, Git, explicit PowerShell, explicit Command Prompt, and npm through an explicitly approved Command Prompt invocation executed successfully. Direct `npm`/`npx`, bare shell built-ins such as `dir`, bare PowerShell cmdlets such as `New-Item`, and a whole command string supplied as an executable were rejected. This explains important classes of failure without proving the contents of earlier chat requests.

The current interface expects an executable and separate argument strings. `npm`/`npx` resolve to Windows batch launchers, which it deliberately rejects unless an explicit shell is requested. Shell built-ins/cmdlets require their shell. A general shell-command interface with visible environment selection is a proposed upgrade, not an existing feature.

The same check ran a real Docker Node command. Its output file remained a proposal until local edit approval, then appeared in the original project. Always distinguish process execution from file application.

## Docker commands

### Docker is installed, but requests fail

The bridge status only reports whether the Docker CLI exists. Verify the engine from the same local user/session that runs the companion:

```sh
docker context show
docker context inspect --format '{{.Endpoints.docker.Host}}'
docker info --format '{{.OSType}}'
```

The runner currently removes user-specific environment settings. A local check found that Docker selected a different endpoint under that minimal environment than in the inherited user environment; both worked here, but context selection needs to be made explicit in the upgrade.

The engine must be local (`unix://` or `npipe://`) and report `linux`. Start Docker Desktop, select Linux containers, and check access permissions. A denied engine pipe can be a session access restriction rather than a missing engine.

### The image is unavailable

Prepare one supported image locally and choose the same image in the panel:

```sh
docker pull node:24-alpine
docker image inspect node:24-alpine
```

Other supported selections are `python:3.12-alpine` and `alpine:3.21`. There is no automatic pull/build or arbitrary image/container selector in 3.1.1.

### There is no way to connect an existing container

That capability is not implemented. The bridge creates a new short-lived container for each command. Persistent project containers, inspected mount mappings and an attachment workflow are [proposed upgrades](roadmap.md).

### Packages or files disappear between commands

Each job gets a fresh filtered copy, with dependencies, `.git`, sensitive paths and runtime state excluded. The container root is read-only and networking is off unless locally enabled. Changes to the temporary copy become at most 20 eligible text proposals when write permission is enabled. The copy is deleted after the job; it is not a persistent development environment. Read-only root filesystems and an unprivileged user can also prevent package installation.

### Docker printed success but the real project is unchanged

Inspect `changes`, apply eligible proposals locally, and read back the original files. Session writes only apply eligible supported changes. Deleted files, binary edits, new nested folders, limits and conflicts can leave the host project different from the temporary copy.

## Workspace errors

Use the latest `workspace_id` from `bridge_status`. Select a regular local project folder rather than a drive root, home directory, link or runtime folder. Paths must be relative and use forward slashes. Sensitive/excluded files, linked files, binary text reads and oversized files are rejected.

Creating a new file requires an existing parent directory. Directory creation, renaming and deletion are not exposed by current workspace tools. A hash mismatch means the file changed; read it again before proposing another edit. Do not overwrite competing changes.

## Permissions or jobs keep disappearing

Saving configuration changes and pausing revoke pending grants/jobs, clear edit proposals and replace the workspace ID. Restarting resets permissions and in-memory job history. Refresh status after every change. These are current session semantics, not durable task continuation.

## The Site cannot connect

Keep the companion and tunnel running. Use the current printed remote HTTPS endpoint, not a localhost control URL or an endpoint from a previous Quick Tunnel. Save the key only in your own private Site. If unchanged, leave the key field blank when updating just the endpoint. Check account/workspace availability and plugin selection separately from local companion readiness.

The local panel and RPC transport are separate listeners. Never fix a connection problem by exposing the local control port.

## Long-running work stops

Current command timeout is at most 120 seconds, output is bounded to 64,000 bytes, and a session retains at most 30 jobs. Restart requires fresh permissions and may change the tunnel endpoint. The bridge does not yet save task plans, resume jobs, run a local agent or subscribe ChatGPT to task events. A skill alone cannot extend a platform session or send another prompt after a turn ends. Both checkpoint-based ChatGPT resume and an optional local agent are in the [proposed design](superpowers/specs/2026-10-26-web-bridge-upgrade-design.md).

## Development checks do not start

Run from the canonical source root. Install Node.js 22.13+ and Python 3.10+. If Python reports `No module named pytest`, install pytest in your development environment before running the Python suite. Build before worker tests: those tests read the generated `dist/server/index.js`. Optional real Docker/browser fixtures need their local dependencies and explicit test setup.
