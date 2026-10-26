# Architecture

Web-Bridge has two runtime halves: a private ChatGPT Site worker and a Python companion running on the owner's computer. A reusable setup plugin helps owners deploy **their own** Site; it is not part of a live request.

## Request path

```text
ChatGPT → Site-generated MCP plugin
           │
           ▼
worker/runtime.js (private Site)
  - identifies the signed-in Site user
  - validates the tool schema
  - loads that user's encrypted connection settings
  - forwards JSON-RPC/MCP over authenticated HTTPS
           │
           ▼
cloudflared Quick Tunnel (optional for remote access)
           │
           ▼
bridge/server/bridge.py (authenticated loopback RPC)
           │
           ▼
bridge/server/companion.py
  ├─ approved-origin HTTP and optional browser operations
  ├─ selected-project listing, text read/search/edit
  └─ approved command jobs (Docker or host)
```

The local control UI is a **separate loopback listener**, not an endpoint that should be exposed by the tunnel. Permission changes, project selection, target origins, host-command approvals, and session revocation are local-only.

## Source ownership

| Source | Responsibility |
| --- | --- |
| `worker/runtime.js` | Site UI routes, MCP surface, authentication, connection forwarding |
| `worker/interface.html` | Private Site connection interface |
| `bridge/launch.py` | RPC/control startup, authenticated tunnel, runtime credentials |
| `bridge/bundle-entry.py` | Single-file `.pyz` extraction and independent runtime directory |
| `bridge/server/bridge.py` | Bounded RPC / target HTTP plumbing |
| `bridge/server/companion.py` | Local tool routing and permission enforcement |
| `bridge/server/control.py` | Owner-facing control-plane API |
| `bridge/server/workspace.py` | Scoped and filtered workspace operations |
| `bridge/server/jobs.py` | Command lifecycle, approvals, container execution |
| `bridge/server/network.py` | Target network handling |
| `bridge/server/oauth.py` | Authentication support |
| `bridge/BRIDGE_TOOLS.json` | Tool contracts shared into the built worker |
| `db/schema.ts`, `drizzle/` | Connection storage schema and migrations |
| `setup-plugin/` | Guided creation of a new account-owned Site |
| `scripts/` | Build, packaging, validation, local preview |

## Security model

The Site authenticates the user and encrypts saved connection credentials using the Site's configured encryption key. The companion separately authenticates incoming RPC traffic. The Site does not have a tool that can grant local file, CTF, host-execution, or network permissions.

The locally selected workspace bounds **workspace tools** and staged container copies, not approved host commands. Host commands execute with the computer user's privileges after exact local approval. Docker uses a filtered copy rather than a mount of the entire selected project; networking is an independent local permission.

The CTF HTTP client can contact only locally approved origins, with controlled redirects and DNS behavior. The browser and HTTP sessions do not share cookies.

A Site plugin, local tunnel, and connection key are all needed for remote operations. Treat the connection key and local control code as secrets. Runtime state must never be committed or copied into a public release.

## Execution lifecycle

1. The model submits a command once, supplying the active workspace identifier and an idempotency key.
2. The companion checks its current permissions, records a bounded job, and requests approval when required.
3. The owner approves **exact** host-command arguments locally; container commands follow the configured container policy.
4. The model polls the job ID, rather than submitting duplicates.
5. Tool output and eligible changes are returned with explicit state. A successful exit code does not prove a visible desktop window or completion of a higher-level task.

Jobs and permission grants are session-scoped. See [Companion reference](bridge/README.md) for limits and runtime details.

## Building and release boundaries

Run commands from the **source root**, not the extracted release folder.

```text
scripts/package-bridge.py    → outputs/Web-Bridge.pyz
                             → outputs/web-bridge-companion.zip
scripts/package-setup.py     → outputs/web-bridge-setup-plugin.zip
                             → outputs/web-bridge-portable-source.zip
scripts/build.mjs            → dist/server/index.js
                             → dist/.openai/hosting.json
scripts/package-release.py   → outputs/Web-Bridge-Open-Source-Release.zip
                             → outputs/SHA256SUMS
```

The portable-source ZIP is sanitized for publication and fresh Site setup. The companion bundle and setup plugin are **generated output**. Do not edit them independently or include private Site identity, workspace state, or credentials when making a release.

## Current limitations

The bridge does not expose desktop screenshots, GUI input, long-lived interactive terminal APIs, unrestricted shell access, or permission changes through MCP. File tools handle bounded UTF-8 files; arbitrary binary edits and filesystem deletion are not exposed as file tools. Container availability and optional browser support depend on local installations.

[README](README.md) · [Setup](SETUP.md) · [Security](SECURITY.md)

## Current execution and synchronization gaps (3.1.1)

The job runner currently sets `completed` after a process exits even when its exit code is nonzero. The RPC `isError` flag is based on an `error` field, so callers must inspect the job's exit code, output and requested effect. Approval is permission to launch, not proof of execution. A local temporary-fixture check reproduced an exit code of 7 with state `completed`; a separate command successfully wrote a proof file. The original reported no-effect command has not yet been reproduced through the full ChatGPT path.

Container jobs are fresh filtered snapshots, not live project containers. The staged `/workspace` mount is writable while the container root filesystem is read-only. Reconciliation proposes at most 20 eligible text changes when writes are enabled; it does not apply deletions or create missing parent directories. The stage is removed after execution. There is no existing-container attachment or persistent dependency environment.

Commands currently have a 120-second ceiling, 64,000-byte output bound and 30-job session cap. Job and edit state is in memory. No local skill registry, upstream MCP client, autonomous runner, durable task store or MCP Events subscription API is implemented. These gaps are tracked in the [proposed upgrade design](docs/superpowers/specs/2026-10-26-web-bridge-upgrade-design.md).

## Documentation ownership

The enclosing repository README and `docs/images/` contain the supplied illustrations. Their captions distinguish conceptual labels and future features from the current implementation. Source documentation is self-contained text so its portable archive and embedded setup plugin do not require the large image assets. The packaging manifest includes source setup, architecture, contributor, companion and nested documentation files.

Use [Usage](docs/usage.md) for actual tool arguments and limits, [Troubleshooting](docs/troubleshooting.md) for result interpretation, and [Documentation index](docs/index.md) for the complete guide list.
