# Use Web-Bridge 3.2

[Documentation index](index.md) · [Setup](../SETUP.md) · [Troubleshooting](troubleshooting.md)

Call `bridge_status` before project work. Use its current `workspace_id`; saving permissions/restarting invalidates old session IDs. Tools cannot grant permissions or approve their own requests.

## Tool inventory

The canonical [tool catalog](../bridge/BRIDGE_TOOLS.json) contains 27 tools:

| Area | Tools |
| --- | --- |
| Status | `bridge_status` |
| Files | `workspace_list`, `workspace_read`, `workspace_search`, `workspace_edit`, `workspace_operation` |
| Commands | `command_request`, `command_status`, `command_cancel`, `docker_status` |
| Integrations | `skill_list`, `skill_read`, `mcp_tools`, `mcp_call` |
| Saved tasks | `task_create`, `task_list`, `task_read`, `task_checkpoint`, `task_verify` |
| HTTP/browser | `list_targets`, `http_request`, `http_batch`, `inspect_html`, `session_cookies`, `reset_session`, `browser_action`, `request_history` |

## Read and change files

Paths are project-relative, with forward slashes and no leading `/`. Sensitive/excluded paths, links and traversal are rejected. File tools are scoped to the selected folder; that scope does not constrain host commands or live Docker mounts.

```json
{"workspace_id":"<current-id>","path":"README.md"}
```

Use the `workspace_read` response hash when calling `workspace_edit` on an existing file:

```json
{"workspace_id":"<current-id>","path":"README.md","expected_sha256":"<read-hash>","text":"Updated content\n"}
```

For a new absent file, omit the hash. Approved creation can make missing parent folders, for example `notes/release/check.md`. Existing content must match the supplied hash. The response includes an edit proposal; inspect `approval_required` and any `result`. Approve in the local panel unless session text writes are enabled. Read back the real file before reporting success.

`workspace_operation` handles folders, moves and recoverable deletion:

```json
{"workspace_id":"<current-id>","operation":"mkdir","path":"notes/archive"}
```

```json
{"workspace_id":"<current-id>","operation":"move","path":"notes/check.md","destination":"notes/archive/check.md","expected_sha256":"<current-file-hash>"}
```

```json
{"workspace_id":"<current-id>","operation":"delete","path":"notes/archive/check.md","expected_sha256":"<current-file-hash>"}
```

After the approved deletion returns `trash_id`, request restore to the intended absent path:

```json
{"workspace_id":"<current-id>","operation":"restore","path":"notes/archive/check.md","trash_id":"<returned-trash-id>"}
```

File move/delete requires its current hash. Nonempty-folder deletion needs `recursive: true` and a separate local recursive-delete grant. Folder operations have their own approval/session grant, distinct from text edits. Conflicts preserve existing data instead of replacing the destination. Deletion is a recoverable move into excluded local project trash, not a permanent purge; keep its runtime recovery record. Text writes may return a local `recovery_path` holding the original inode on POSIX. Preserve and inspect that path, including after an apparently successful write, before local cleanup: an external process may still write through an already-open descriptor.

## Submit a command once

The local profile chooses `host`, `container` (snapshot), or `docker` (live project), shell and timeouts. Omit `environment` to follow it; conflicting explicit environments are rejected rather than silently switching modes.

Use shell text for normal terminal syntax. This Windows example assumes a locally selected host/Command Prompt profile:

```json
{"workspace_id":"<current-id>","command":"npm --version","shell":"cmd","cwd":"","timeout_seconds":30,"idempotency_key":"npm-check-0001"}
```

For PowerShell use the installed configured shell and valid PowerShell syntax. In Linux Docker use `sh` or installed `bash`:

```json
{"workspace_id":"<current-id>","command":"node --version && printf 'bridge-check\n'","shell":"sh","timeout_seconds":30,"idempotency_key":"node-check-0001"}
```

For an exact native executable use an argument array instead:

```json
{"workspace_id":"<current-id>","argv":["python","-c","print('bridge-command-check')"],"cwd":"","timeout_seconds":30,"idempotency_key":"python-check-0001"}
```

Never supply both `command` and `argv`, or place a whole command line in `argv[0]`. Direct Windows `.cmd`/`.bat` execution is rejected in exact-argv mode: use `command` with `shell: "cmd"` for npm/npx. The command's exact shell text/arguments are visible to the local owner. Host mode always needs individual approval; snapshot/live Docker can use the separate local container-command session grant.

`cwd` is relative to the selected project; empty means its root. Host subprocesses receive a minimal environment, so another terminal's virtualenv, credentials or custom variables may be absent. Host commands use OS-account privileges beyond the project, including networking.

Retain the returned `job_id` and poll `command_status`:

```json
{"job_id":"<returned-job-id>","output_offset":0}
```

For incremental output, pass the previous `next_output_offset`. Offsets count characters in bounded combined stdout/stderr. A truncated result is not a complete output archive.

| State | Meaning |
| --- | --- |
| `pending` | Awaiting local approval; not executed |
| `approved` | Queued to launch; not successful yet |
| `running` | Launched; inspect output/launch evidence |
| `completed` | Process exited zero; inspect `success`, output and intended effect |
| `failed` | Nonzero exit or execution/launch failure; inspect exit/error evidence |
| `timed_out` | Configured execution timeout reached |
| `cancelled` | Cancellation/revocation stopped the job |
| `denied` / `expired` | Permission to launch was not obtained |

A nonzero process exit reports `success: false`; the 3.1 misleading-completed behavior is fixed. For timeout/cancellation, keep polling while `cleanup_pending` is true. A public terminal outcome can precede process-group cleanup; do not start competing mutations before cleanup settles.

Use `command_cancel` with the job ID to cancel. Reuse an idempotency key only for an identical retry under the same policy. Changed commands/policy need a new key. Durable receipts prevent identical submissions from executing twice; older output may be omitted and marked `history_archived`. Restart preserves receipts for local inspection and never resumes or reapproves them automatically. Keys cannot be reused across a changed companion session; inspect the old outcome before preparing any new request. If a response is lost, inspect the existing job/effect before any resubmission.

A zero exit does not prove that a GUI appeared, a server is healthy, or the whole assignment is complete. Verify the requested result separately.

## Snapshot versus live Docker

**Snapshot (`container`)** uses a fresh filtered copy at `/workspace`, a read-only container root and a writable staged project. The original is not mounted. Choose a supported pre-pulled image locally; networking is off unless granted. Snapshot exclusions include Git, dependencies, runtime/credentials and links, so full development workflows may need live Docker instead.

Eligible nested text creates/edits and deletions become proposals when applicable permissions allow. Text and deletion operations follow separate approval policies. Inspect all `changes`, errors, conflicts and `snapshot` fields; process success does not imply full reconciliation. Unsupported, excluded, over-limit or conflicting results retain a local snapshot with an artifact ID. Inspect it locally and use **Discard retained snapshot** only when no longer needed. Retained artifacts are bounded to ten.

**Live project (`docker`)** uses the locally configured persistent container and validated real-project mount. Call `docker_status` with the current workspace ID. Setup/pull/create/attach/start/stop/remove/log actions are local owner actions, not MCP permission tools. Context/endpoint and mapping are pinned. Live files change directly, including through commands, without snapshot reconciliation. The bridge never mounts the Docker socket for a managed project; selected attached containers are inspected for rejected/broader access. Only bridge-owned containers may be stopped/removed through its controls. Cancellation targets the command group, not the whole attached container. See [Setup](../SETUP.md#docker-modes).

## Selected skills and application adapters

Enable integrations locally. `skill_list` includes the built-in `web-bridge-project-work` and explicitly selected local skill folders. Load instructions/resources with `skill_read`:

```json
{"workspace_id":"<current-id>","name":"web-bridge-project-work","resource":"SKILL.md"}
```

Skills are workflow input; they do not install dependencies or authorize tools. For applications, configure trusted stdio or Streamable HTTP MCP adapters locally, with explicit allowed tools. `mcp_tools` lists selected schemas; `mcp_call` takes `server`, `tool`, `arguments` and the workspace ID. Schemas are validated, configured credentials are redacted from exposed configuration/results, and calls are not automatically retried. After interruption inspect the application state before retrying a mutation. Adapters can have broader authority than workspace tools; no arbitrary app GUI control is automatic.

## Durable tasks and continuation

Create a substantial task with machine-checkable acceptance criteria:

```json
{"workspace_id":"<current-id>","intent":"Create the release note and verify its text","checks":[{"kind":"file","path":"notes/release.md","contains":"Release ready"}]}
```

File checks use relative `path`, optional `contains` and/or `sha256`; command checks use `{"kind":"command","job_id":"<successful-job-id>"}`. Other/text-only entries need explicit review and do not automatically pass. Empty checks do not verify completion. Preserve the intended criteria rather than weakening them to mark done.

Checkpoint actual evidence, existing job/proposal IDs, remaining work and blockers:

```json
{"workspace_id":"<current-id>","task_id":"<task-id>","status":"partial","handoff":"Release note written; read back and verify next.","evidence":[{"path":"notes/release.md"}],"expected_revision":1}
```

Use the latest returned revision, not a hard-coded value. Available checkpoint statuses are `partial`, `blocked`, `awaiting_approval` and `queued`; machine-verified completion goes through `task_verify`. To refine checks after evidence becomes available, include `checks` and the current `expected_revision` in `task_checkpoint`; preserve every existing requirement. A text requirement can become a structured check retaining that exact text as its `label`; existing structured requirements cannot be weakened or removed. `task_list` / `task_read` recover durable SQLite records and handoff. After restart/session change the owner selects **Use in ChatGPT** locally to rebind the task. File checks can run again; command checks from a previous session require local receipt inspection and fresh current-session verification rather than an assumed old success.

Call `task_verify` with task/workspace IDs. It checks actual file contents/hashes and successful command evidence and marks the task machine-verified complete only when configured checks pass. For manual/text criteria, the owner can use **Confirm reviewed complete** in local Saved work after personally reviewing the result; it records owner-review evidence rather than claiming machine verification. Task records are not a replay queue. An interrupted mutation has an uncertain outcome until its effect is inspected. Writer leases serialize bridge mutations between ChatGPT, jobs and the local runner; unrelated editors/processes still require conflict checks.

**ChatGPT mode:** checkpoint and resume on the next prompt. Automatic task-event prompts are not enabled (`chatgpt_events: false`); a skill cannot send a new prompt or extend platform limits.

**Optional local agent:** install its separate dependency, select a model/API-key environment-variable name and budgets locally, then explicitly start a saved task. It can continue independently within those limits, uses the same tool permissions, and stops for required approvals. Budgets are steps/time/tokens, not a fixed dollar price. Save setup makes no API call. See [Setup](../SETUP.md).

## Approved HTTP and optional browser

Configure named exact origins locally, with separate opt-in for private lab addresses. `list_targets` lists them. `http_request` / `http_batch` take target names and bounded relative paths; redirects are not followed. `inspect_html` extracts forms/links, `session_cookies` returns metadata without cookie values, `reset_session` clears a target session, and `request_history` returns bounded evidence metadata.

`browser_action` needs locally installed Playwright/Chromium and approved origins. It supports visit/snapshot/click/fill/press/evaluate/diagnostics, not general desktop input. Browser and HTTP cookies are separate; WebSockets and service workers are blocked.

## Limits and persistence

| Item | Behavior |
| --- | --- |
| Text file | 256,000 bytes; UTF-8 |
| Directory listing / search | Up to 500 entries / 50 matching lines |
| Workspace walk/snapshot | 5,000 entries / 50,000,000 snapshot bytes |
| Pending text edits | Up to 20; approval expires after 300 seconds |
| Command timeout | Default 600 seconds; within local maximum, at most 3,600 |
| Exact argv | 1–50 bounded strings |
| Captured command output | 64,000 bytes, combined stdout/stderr |
| Jobs | Up to 30 active; dashboard 200 rows; newest 160 detailed durable receipts, older identity/idempotency tombstones retained |
| Snapshot reconciliation | Up to 20 changed-file proposals and 20 deletion proposals; excess reported |
| Retained snapshots | Ten; local inspection/discard required when full |
| MCP adapters | Explicit tool allowlist; 0.1–120-second per-operation timeout; bounded responses |
| Local agent | Up to 100 steps, 3,600 seconds, 1,000,000 tokens per configured run |

Connection credentials, selected integration/Docker configuration and task records persist locally. Permissions and pending approvals are session state. Command receipts and idempotency tombstones persist locally in SQLite; they are inspection-only after restart and cannot be reapproved or replayed. Potentially unfinished executions require explicit local stopped/reviewed confirmation before new writes in that project. Runtime data, recoverable content and retained snapshots may contain private source; do not publish them.
