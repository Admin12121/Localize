# Illustrated Web-Bridge workflows

[Project README](../README.md) · [Architecture](../source/ARCHITECTURE.md) · [Actual tool examples](../source/docs/usage.md)

These eight owner-supplied illustrations are preserved without image edits and named by subject. Their embedded API names, labels and examples are conceptual, not the 3.2 contract. Captions below describe the actual implementation and remaining limits.

## 1. System architecture

![Private Site, companion and controlled local resources](images/01-system-architecture.png)

The high-level request path is accurate. The Site forwards authenticated calls; local controls grant access. Docker now supports filtered snapshots and locally configured live project containers with explicit image preparation/attachment. Automatic image building is not provided. “Safe shell commands” is not a host security boundary: approved host jobs use the owner's OS account beyond the project. The private Site runs on Sites infrastructure.

## 2. Host command lifecycle

![Host command approval, execution and polling](images/02-host-command-lifecycle.png)

Use `command_request` and `command_status`, not `run_command`. Use `command` plus a configured shell, or exact `argv`, never both. Host commands always need exact local approval and are not isolated. Default timeout is 600 seconds; the owner-selected maximum is at most 3,600. Output combines stdout/stderr and is bounded. Nonzero exit is now `failed` with `success: false`; timeout and cancellation differ. Approval is not execution evidence; inspect results, cleanup and actual effects.

## 3. Isolated Docker job

![Filtered Docker snapshot and separate change approval](images/03-docker-snapshot-job.png)

Snapshot mode is `container` in the local command profile; there is no `docker.run` tool. Choose a supported pre-pulled image locally. The container root is read-only, while the filtered `/workspace` copy is writable; the original project is not mounted. Eligible nested creates/edits and deletions become proposals under separate text/operation permissions. Unsupported, excluded, conflicting or excess changes are reported and retain an artifact for local inspection. Snapshot limits remain 50 MB/5,000 entries; this is distinct from live Docker sharing.

## 4. Workspace edit lifecycle

![Hash-checked text proposal, local review and application](images/04-workspace-edit-lifecycle.png)

Use `workspace_edit`, `text` and the current `expected_sha256` for an existing file. Omit the hash only for an absent new file; approved creation can make missing parents. Paths are relative without a leading `/`. `workspace_operation` separately proposes mkdir, move, recoverable delete and restore. Recursive deletion needs its own grant. Proposals are not applied effects; inspect results/readback. Preserve a reported local recovery path until inspected. File scope is not process isolation.

## 5. Approved HTTP request

![Origin validation, bounded HTTP request and evidence](images/05-approved-http-request.png)

The actual tool is `http_request`; `target` is the configured local target name. HTTP/HTTPS exact origins are supported, with separate local permission for private labs. Redirects are not followed. Cookies/evidence are bounded session data, not an unlimited permanent archive. These origin controls do not constrain host-command or selected adapter networking.

## 6. Build, deploy and connect

![Source builds, private Site setup and companion connection](images/06-build-deploy-connect.png)

Use canonical `source/`, `npm run build` and documented package scripts; the pictured layout and build names are illustrative. The Site gateway forwards calls; the optional independently running agent lives locally and needs separate explicit setup/start. Use the printed authenticated HTTPS endpoint remotely, never a localhost control URL. Illustrated keys are placeholders; never screenshot real ones. Building a local package does not update an installed Site/plugin. Follow [Setup](../source/SETUP.md).

## 7. Broader workflow concept

![Expanded bridge, Docker and application-adapter concept](images/07-expanded-workflow-concept.png)

3.2 implements local Docker preparation/create/attach controls, selected skill/MCP adapters and durable tasks with an optional local runner. Image preparation is explicit, not automatic. Arbitrary desktop screenshots/input and application discovery are not automatic capabilities: a selected adapter defines app access. Permissions remain local. ChatGPT resumes saved work on the next prompt; automatic task-event prompts are not enabled.

## 8. Expanded architecture concept

![Expanded architecture, job flow, Docker and application concepts](images/08-expanded-architecture-concept.png)

This remains a concept rather than an implementation specification. Actual modules live under `source/bridge/server/` and `source/worker/`; generic tool names/layout labels are illustrative. Snapshot mounts are writable copies despite the pictured read-only label; live Docker maps the real project. SQLite tasks/checkpoints and local runner budgets are implemented, but not unlimited durable audit, arbitrary GUI control or automatic ChatGPT continuation. Consult [Architecture](../source/ARCHITECTURE.md) and [release scope](../source/docs/roadmap.md).

## Original filename map

| Original filename | Organized filename |
| --- | --- |
| ChatGPT Image Oct 26, 2026, 02_18_40 AM-1.png | 01-system-architecture.png |
| ChatGPT Image Oct 26, 2026, 02_18_41 AM-2.png | 02-host-command-lifecycle.png |
| ChatGPT Image Oct 26, 2026, 02_18_42 AM-3.png | 03-docker-snapshot-job.png |
| ChatGPT Image Oct 26, 2026, 02_18_44 AM-4.png | 04-workspace-edit-lifecycle.png |
| ChatGPT Image Oct 26, 2026, 02_18_45 AM-5.png | 05-approved-http-request.png |
| ChatGPT Image Oct 26, 2026, 02_18_46 AM-6.png | 06-build-deploy-connect.png |
| Web Bridge Workflow Architecture Diagram.png | 07-expanded-workflow-concept.png |
| Web-Bridge Architecture Workflow Infographic.png | 08-expanded-architecture-concept.png |
