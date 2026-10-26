# Architecture

Web-Bridge 3.2 has a private ChatGPT Site gateway and a Python companion on the owner's computer. The setup plugin provisions an owner's Site; it is not part of each runtime request.

## Request and control paths

```text
ChatGPT → Site-generated MCP plugin → worker/runtime.js
                                      ├─ authenticates Site user
                                      ├─ validates tool schema
                                      └─ decrypts saved connection and forwards RPC
                                                        ↓ authenticated HTTPS
                                             optional cloudflared tunnel
                                                        ↓
bridge/server/bridge.py → companion.py + project_services.py
                          ├─ scoped files / recoverable operations
                          ├─ host, snapshot and live Docker jobs
                          ├─ selected skills / MCP adapters
                          ├─ SQLite tasks / writer leases / optional runner
                          └─ approved HTTP / optional Chromium

Separate loopback control.py + control.html
  → owner-only project/grants/approvals, Docker, adapters, tasks and runner setup
```

Only authenticated RPC is exposed by the tunnel. The local control listener remains loopback-only. No MCP tool changes project selection, grants permissions, configures an adapter, approves a host job or starts the optional agent on the owner's behalf.

## Source ownership

| Source | Responsibility |
| --- | --- |
| `worker/runtime.js`, `worker/interface.html` | Private Site routes, authentication, encrypted connections, MCP forwarding |
| `bridge/launch.py`, `bridge/bundle-entry.py` | RPC/control startup, tunnel, private runtime and bundle extraction |
| `bridge/server/bridge.py` | Bounded authenticated RPC and approved-target HTTP plumbing |
| `bridge/server/companion.py` | Session permissions, tool routing and command profile enforcement |
| `bridge/server/project_services.py` | File/Docker/integration/task coordination and writer leases |
| `bridge/server/control.py`, `bridge/control.html` | Owner-only setup, approvals and local task/runner controls |
| `bridge/server/workspace.py` | Filtered scoped reads/search, hash-checked text edits, platform-safe publication |
| `bridge/server/file_operations.py` | Bounded mkdir/move/delete/restore with recovery and collision checks |
| `bridge/server/command_launch.py` | Explicit shell text versus exact executable/argv resolution |
| `bridge/server/jobs.py`, `bridge/server/process_group.py` | Job approvals, process evidence/output, outcomes, cancellation and snapshot reconciliation |
| `bridge/server/docker_project.py` | Pinned local context, persistent mapped project/container lifecycle and per-exec cancellation |
| `bridge/server/integrations.py` | Selected skill roots, optional stdio/HTTP MCP sessions, allowlists/schema validation/redaction |
| `bridge/server/task_store.py` | SQLite tasks/checkpoints/evidence, revisions, project rebinding and writer leases |
| `bridge/server/agent_runner.py` | Optional explicit API runner, budgets, checkpointing and uncertain-mutation handling |
| `bridge/server/network.py`, `browser_process.py`, `oauth.py` | Approved networking, optional browser isolation and authentication support |
| `bridge/skills/project-work/SKILL.md` | Built-in evidence/checkpoint workflow instructions |
| `bridge/BRIDGE_TOOLS.json` | Canonical 27-tool contract used by the worker and companion |
| `db/schema.ts`, `drizzle/` | Site encrypted connection storage and migrations |
| `setup-plugin/`, `scripts/` | Provisioning, builds, packaging, validation and sanitized source export |

## Execution and authority

The local profile selects environment, shell and default/max timeout. `command_request` accepts shell text or exact argv, never both. A conflicting explicit environment is rejected. Jobs are submitted once with a session idempotency key, approved under local policy, and polled by ID. Nonzero exit is `failed`; zero exit is `completed`; timeout/cancellation are distinct. `success`, exit/output/launch evidence and `cleanup_pending` separate process outcome from cleanup and task verification.

Host jobs always need exact local approval and run as the OS account. Workspace scope and file exclusions do not sandbox them. Snapshot and live Docker jobs may use the local container-command session grant. Command timeouts default to 600 seconds and are capped by the owner-selected maximum up to 3,600 seconds. Output is bounded; the dashboard retains 200 compact rows and the newest 160 detailed durable receipts. SQLite records queue/launch identity and outcomes before/after execution. Restart never reruns a receipt: potentially unfinished work becomes interrupted with outcome-unknown recovery evidence. Fresh grants are required; prior-session command details are local inspection only. New writes in the affected project remain blocked until the owner confirms that interrupted work is stopped/reviewed.

| Mode | Project access | Lifecycle |
| --- | --- | --- |
| Host | Real files under OS-account authority, beyond workspace scope | Owned process group/Windows job; per-command approval |
| Snapshot | Filtered copy at `/workspace`; read-only root, writable staged project | Fresh container; bounded reconciliation proposals; unresolved artifacts retained |
| Live Docker | Validated bind mount of selected real project, broader than file-tool filters | Persistent locally created/attached container; context/endpoint pinned; per-exec cancellation |

Live Docker setup/image preparation/attachment are local actions. No automatic pull/build or host fallback occurs. The selected real mount must match; socket exposure is rejected. Broader attached configuration requires local inspection/acknowledgment where supported. Stop/remove only applies to bridge-owned containers. A live command's changes are direct, not an edit proposal.

## Files and recovery

File tools use relative paths, reject excluded/sensitive/link paths and enforce bounded UTF-8 content. Existing text edits and file move/delete require current hashes. Approved absent-file creates can make missing parents. Folder operations have separate approval/session policy and recursive deletion needs its own grant.

Windows writes/renames use pinned native handles; Linux and macOS moves use native exclusive-rename primitives rather than overwrite-prone replacement. macOS code still requires native execution verification. POSIX text publication retains the original inode as a reported `recovery_path`, preserving possible late writes through an external process's open descriptor. Recoverable deletion moves content into excluded project trash with local runtime records; restore validates content and destination conflicts.

Snapshots are bounded to 50 MB/5,000 entries. Reconciliation reports unsupported, excluded, conflicting and excess changes and retains the local artifact when unresolved. Ten retained snapshots require inspection/discard before new snapshot jobs. Success of a command does not imply complete synchronization.

## Integrations and durable work

Core runs on Python 3.10+ without pip packages. Optional MCP adapters use Python 3.11+ and pinned MCP 2.3.0; the optional runner separately uses OpenAI 3.37.0. Skills are selected read scopes plus built-in workflow instructions; they do not provide applications or grant tools. MCP sessions are explicitly configured stdio/Streamable HTTP, expose an allowlist, validate tool arguments, redact configured credentials, and do not retry potentially mutating calls.

SQLite tasks persist intent, acceptance checks, handoff and evidence with revisions and checkpoints. A writer lease coordinates bridge mutations and command lifecycles across ChatGPT and the runner; external editors are handled by conflict checks, not controlled by that lease. After a new workspace session, local **Use in ChatGPT** rebinds a saved task. Interrupted mutations are inspected, not replayed. `task_verify` checks current file contents/hash or successful current-session job evidence. Unsupported/manual checks do not automatically pass. Checkpoint refinement preserves existing requirements and requires the current revision. The owner may explicitly confirm reviewed completion locally; that records owner-review evidence separately from machine verification.

ChatGPT resumes on the next prompt. This build declares `chatgpt_events: false`; it does not subscribe a chat to automatic task prompts. The optional local runner starts only by an explicit owner action with configured model, API-key environment-variable name and step/time/token budgets. It uses the same permissions/approvals and separately billed API access. Budgets are not a dollar guarantee.

## State and release boundaries

Credentials, Docker/integration configuration and task SQLite data persist in the private runtime. Grants, approvals, job history and idempotency receipts remain session state. Recovery/trash/snapshot artifacts can contain private project content and are not release inputs.

```text
scripts/package-bridge.py  → outputs/Web-Bridge.pyz
                          → outputs/web-bridge-companion.zip
scripts/package-setup.py   → outputs/web-bridge-setup-plugin.zip
                          → outputs/web-bridge-portable-source.zip
scripts/build.mjs          → dist/server/index.js + hosting configuration
scripts/package-release.py → outputs/Web-Bridge-Open-Source-Release.zip
                          → outputs/SHA256SUMS
```

Build from the canonical source root. Generated bundles/distribution copies are rebuilt, not independently edited. Sanitized portable source omits deployment identity and runtime data. Large repository illustrations stay outside its text documentation payload. Building artifacts does not publish an installed Site/plugin.

[README](README.md) · [Setup](SETUP.md) · [Usage](docs/usage.md) · [Security](SECURITY.md)
