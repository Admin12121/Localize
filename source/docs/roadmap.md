# Release scope and next steps

[Documentation index](index.md) · [Original upgrade design](superpowers/specs/2026-10-26-web-bridge-upgrade-design.md)

## Implemented in 3.2

- Command profiles select host, filtered snapshot or live Docker, shell and timeouts. Nonzero exits report failure; timeout and cancellation are distinct. Incremental output, cleanup status, rolling history and session idempotency receipts support precise follow-up.
- Workspace tools create nested text files and folders, move entries, recoverably delete and restore. Hash/conflict checks, separate operation/recursive permissions and retained recovery content protect concurrent work.
- Live Docker controls check the local engine, explicitly prepare an image, create a project container or validate attachment. Context and project mapping are pinned; only managed containers can be stopped/removed by those controls. Snapshot reconciliation reports unsupported/unresolved changes and retains artifacts.
- Selected local skill folders and allowlisted stdio/HTTP MCP adapters are available with optional dependencies. A built-in project-work skill explains checkpoints and evidence. Application capabilities come from the selected adapter.
- SQLite tasks store checks, handoff and evidence. Writer leases coordinate bridge mutations. ChatGPT resumes saved work on the next prompt; an optional explicitly started API runner can continue independently within configured budgets and permissions.

See [Usage](usage.md) for the actual 27-tool catalog and limits. The dated design records intent; it does not override the implemented contract.

## Current boundaries

Automatic ChatGPT task-event prompts are **not enabled** (`chatgpt_events: false`). A skill cannot send another prompt or extend a platform session. Saved tasks do not replay interrupted mutations. Resume by inspecting evidence and current state; completion requires actual acceptance checks.

The optional local agent needs separate API credentials, an explicit model, optional Python packages and a local Start action. Its step/time/token limits do not guarantee a fixed cost or unlimited operation. ChatGPT-based use remains available without it.

There is no general desktop screenshot/input automation, arbitrary application discovery, interactive terminal streaming or automatic image-build pipeline. Workspace text edits and snapshots remain bounded. Host and live Docker commands have broader access than file-tool filters. Snapshot changes can be unsupported, conflicting or over limits and need local review; retained artifacts are not complete project synchronization.

macOS uses the native exclusive-rename API for collision-safe operations, but that platform path still needs native macOS execution verification before claiming tested parity. Optional dependencies and local engine/application availability remain setup requirements.

## Deployment and follow-up

Locally built 3.2 source, setup package, companion and gateway artifacts do not automatically publish an existing private Site or update an installed plugin. Deployment must be performed separately while preserving the owner's Site identity, encryption secret, database, connection key and sharing settings.

Further work can expand platform verification, supported acceptance-check types and application-specific adapters, and evaluate supported ChatGPT event continuation for the actual host/account. Any such expansion needs explicit implementation and verification before being advertised as enabled. Do not turn automatic prompts, fixed-cost guarantees or universal application control into documentation promises.
