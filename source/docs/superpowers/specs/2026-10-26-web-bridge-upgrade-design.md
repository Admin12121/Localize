# Web-Bridge upgrade design

Date: 2026-10-26 (Asia/Katmandu). Status: proposed; implementation has not started.

## Intent and agreed direction

Make the existing project dependable before updating the installed plugin. ChatGPT should work on the selected project, including creating folders/files, reading, editing, deleting, and running commands in the locally configured environment. The owner needs understandable Docker configuration and access to selected local skills, MCP servers, and application integrations. Work must record its progress, verify results, and resume without pretending it has finished.

The owner requested both interactive ChatGPT use and an optional local agent for automatic continuation. These will share the same project policy, task records, tools, and execution evidence. The existing Python companion and JavaScript Site worker remain the foundation. No deployment or installed-plugin change is part of the first project phase.

## Current evidence

- Canonical development source is `source/`; the repository also contains generated `Companion/`, `Plugin/`, and `Web-Bridge.pyz` distributions. Version is 3.1.1.
- `bridge/server/jobs.py` queues jobs and actually launches processes. A local temporary-fixture diagnostic successfully wrote a proof file and returned output with exit code 0. The reported original failure is not yet reproduced end to end through ChatGPT.
- A second diagnostic exited with code 7 but still returned state `completed`. The RPC error flag currently depends on an `error` field, rather than the command's terminal outcome. This can make unsuccessful execution look successful to a client.
- Docker uses a fresh filtered snapshot per command, destroys that snapshot afterward, proposes at most 20 text changes, and never applies deletions. New nested folders are not created by workspace edits. There is no persistent development container or existing-container attachment workflow.
- Commands have a 120-second limit, 64 KB output cap, and 30 retained jobs per companion session. Permission changes revoke queued/running work. Jobs, grants, and edit proposals are held in memory.
- The local panel selects one of three pre-pulled images. It does not manage image preparation, container selection, workspace mounts, or connection diagnostics.
- Docker Desktop was verified running a Linux engine. `node:24-alpine` is available; no running containers were listed during inspection. Restricted-session Docker access initially failed, so that result alone was not an engine failure.
- The source includes 16 MCP tools, with no local skill registry, upstream MCP client, desktop application adapter, durable task scheduler, or MCP Events implementation.
- Follow-up runner diagnostics reproduced rejected direct `npm`/`npx` calls (Windows batch launchers), rejected bare `dir`/`New-Item`, and rejected a whole command string supplied as an executable. Python, Node, Git, explicit PowerShell, explicit Command Prompt, and npm through an explicitly approved Command Prompt invocation all ran. This supports an invocation/command-interface problem in addition to inaccurate terminal status; it does not prove every historical command used one of these forms.
- A real Docker Node job ran and proposed its output file. The host file was absent until the separate edit approval, then present. Docker inspection also resolved different endpoints with inherited versus runner-minimal environment: `dockerDesktopLinuxEngine` versus `docker_engine`. Both reported Linux on this machine, but stripping user Docker configuration can select a different endpoint than the owner expects.
- Python 3.14.7 and Node 24.20.0 are available. The active Python installation does not have pytest. Full regression tests have not yet been run.

## Approaches

1. Repair the existing short-lived snapshot bridge only. Lowest initial effort, but it does not provide a shared development environment or automatic continuation.
2. Replace the bridge with a new autonomous agent product. More flexibility, but discards working integration and requires a much larger migration.
3. Extend the existing companion with shared workspace/execution services and a durable task store, used by ChatGPT and an optional agent. Recommended; the owner's request for both modes selects this direction. Detailed mechanisms below are implementation proposals, not already approved policy changes.

## Delivery order

1. Document the actual project, organize supplied diagrams, and establish reproducible execution checks.
2. Repair command outcomes, diagnostics, lifecycle, output polling, and verification evidence.
3. Add complete scoped file operations and understandable host/Docker project configuration.
4. Add selected local skills and MCP/application integrations.
5. Add durable tasks and both continuation modes.
6. Update tool contracts, workflow skills, builds, and installed plugin after the project behavior passes acceptance checks.

Documentation can ship independently. Each runtime stage remains reviewable and tested; no blanket code cleanup or large file move is required first.

## Execution and truthful outcomes

Separate transport success, request acceptance, process execution, and task verification. Define explicit job states: awaiting approval, queued, starting, running, succeeded, failed, timed out, cancelled, denied, expired, interrupted, and outcome unknown. A nonzero exit is `failed`; approval and queue acceptance never count as execution. Preserve existing tool names and support legacy response fields during migration where possible.

Every job records the resolved executable and arguments, environment kind, working directory, submission/start/end timestamps, process/container execution identity where available, exit code or termination reason, bounded output cursors, and artifact/change results. Local diagnostics preserve an actionable error category and safe message instead of hiding all `OSError` details. Keep secrets out of remote output and command logs; local environment secrets must not appear in argument previews.

Command execution is asynchronous. Short RPC calls submit, inspect, cancel, or read incremental logs; the lifetime of an RPC request does not set the command lifetime. Propose a 10-minute command default with an owner-configurable ceiling, plus explicitly started long-lived services. Rotate completed history instead of forcing a restart after 30 jobs. Preserve idempotent submission and never rerun an ambiguous job automatically.

Completion evidence must match the operation. A successful exit is enough to report process success, but does not prove a GUI appeared, a server became healthy, or a project upgrade passed tests. Check the requested file artifact, service health, or validation command before reporting that higher-level result.

### Windows commands and explicit shell support

The interface must support ordinary Windows development commands without making the model guess which names are executable files, batch launchers, or shell built-ins. Retain the exact executable/argument-array path. Add an explicit shell-command path, with the shell chosen from the local project profile and its exact command text visible for approval. The request must contain either an argument array or a shell command, never an ambiguous mixture. Do not silently concatenate arguments or reinterpret shell metacharacters in an existing argument array.

Use tested adapters for installed PowerShell and Command Prompt on Windows, with a separately configured shell for Linux/macOS/Docker. Missing shells and launcher mismatches return an actionable error before approval. Verify npm/npx, shell built-ins, paths with spaces, Unicode, redirection, failed native commands, and cancellation through these adapters. Shell error/exit behavior must be documented and tested; do not convert a failed native command into a successful wrapper exit. Normalized requests must show the actual environment, executable, working directory and shell to the owner before execution.

## One project and locally selected execution

Introduce an owner-managed project profile containing its host root, workspace identity, execution mode, command policy, writable scope, Docker configuration, and integration selections. The owner chooses it locally. Tools may omit environment to use this profile; an explicit conflicting environment request is rejected instead of silently switching modes. Changing profiles invalidates stale tool requests and active write leases.

Host mode uses the selected host directory. Docker development mode uses a persistent managed Linux container with that same selected project mounted at a known path such as `/workspace`. This is deliberately different from filtered snapshot mode: the owner explicitly grants live project access to that container. The UI explains the difference. Snapshot mode remains available for isolated one-off work and keeps its filtered-copy policy.

Do not automatically expose home directories, credentials, unrelated folders, or the Docker socket to a container. Host commands retain their existing OS-account reach; a working directory does not confine them. Exact local approval remains the host default. Any optional session command grants must be configured locally, visibly scoped to the chosen executable/project policy, expire, and be revocable. No tool can grant itself permissions.

## Docker setup and attachment

The local panel provides engine/context readiness checks, image readiness, selected container identity, mount mapping, work directory, network choice, resource limits, status, and logs. Explain each failure with a concrete next action. Image downloads/builds and creation/start of containers are explicit local actions with progress and errors.

Resolve and validate the owner-selected Docker context once, then use that same context/configuration for readiness checks, inspection, creation and execution. Do not rely on a stripped environment that falls back to a different default endpoint. Preserve required local Docker configuration without exposing its credentials to the model or unrelated child processes. Continue rejecting remote engines unless a separately designed local policy explicitly supports them.

Offer two paths: create a managed project container from a selected approved image, or attach a selected existing container. Existing-container attachment must inspect its ID, status, user, mounts, privileged mode, capabilities, and network exposure. For this upgrade, only permit attachment when the chosen host folder is actually mapped to the configured container workspace; reject unmapped containers with a clear explanation. A separate container-only filesystem backend is deferred. This is a proposed implementation choice to keep file tools and commands addressing the same project. Advanced containers with broader access need a clear local grant and must not be described as isolated.

Operations in a persistent Docker project must address the same workspace as file tools. Verify this with a file created through the bridge, read through a container command, modified there, and read back through the bridge. Recheck mount/container identity before mutation. A replaced container requires revalidation.

Managed container ownership is explicit: stop/remove only containers the bridge created and recorded. Attaching to an existing container never grants permission to remove it. Cancellation must stop only the owned command process tree, not an unrelated application or attached container. Use a verified in-container command supervisor/exec process group for attached-container cancellation; if it cannot enforce cleanup, reject cancellable execution rather than claiming success. Live bind mounts preserve user-file visibility; dependency volumes and file ownership need OS-specific checks.

## Complete file operations

Keep existing scoped list/read/search/edit tools and add explicit create-directory, create-file, move/rename, delete-file, and delete-directory operations. Paths remain relative, validated, and protected against escapes, symlinks, junctions, and excluded sensitive paths. Keep UTF-8/bounded-text semantics initially; report unsupported binary operations clearly.

Use content hashes and expected existence for overwrite/delete preconditions. Default directory removal to empty directories only; recursive removal requires an explicitly configured local grant and bounded path preview. Prefer a recoverable local trash area over irreversible deletion. Moves validate both source and destination. Denials and conflicts preserve existing data.

Snapshot reconciliation reports created, modified, deleted, binary, excluded, oversized, and unapplied changes separately. Nested directories needed for approved new files are created safely. Exceeding a reconciliation limit is visible and leaves an inspectable result; it must not silently discard changes and report a fully synchronized project. Do not sync dependency folders or secrets from snapshots.

## Skills, MCP servers, and applications

A skill supplies workflow instructions and optional resources/scripts. An MCP server supplies callable tools. A desktop application is controllable only through an installed adapter/server or a separately configured computer-control capability. Reading a skill does not install or confer its dependencies.

Add a local integration registry with explicit trusted paths and configured MCP endpoints/commands. Discover skill metadata, load selected skill instructions/resources, and report their required tools. Do not automatically import all user-wide skills, MCP credentials, or applications. In a hosted ChatGPT conversation, expose the selected resources through bridge tools; this is not identical to the host's native local skill discovery.

For selected MCP servers, support stdio and streamable HTTP using a maintained protocol SDK, with version selection during implementation after reviewing its current docs. Provide list/connect/health, tool discovery, schema validation, bounded call timeouts/results, and explicit disconnection. Use namespaced tool identifiers and enforce the configured server/tool allowlist on every call. Optional MCP dependencies remain separate from the dependency-free core bundle.

Local stdio servers run on the host unless the owner explicitly configures a Docker integration adapter. Reading Docker workspace content must not silently cause tools to execute on the host. MCP-server permissions and resource reach can be broader than the project and require independent local selection. Authentication stays in local secret storage; logs and tool discovery never return credentials. Test with one fixture skill, one real local fixture MCP server, and one configured application integration before advertising support.

## Durable work and both continuation modes

Use a local SQLite task store outside selected source projects. Store task intent, acceptance checks, steps, status, selected profile, checkpoints, command IDs, evidence, remaining work, blockers, and a concise handoff. Keep it out of releases. Completed evidence is bounded and retention is locally configurable. Do not persist credentials in task text.

Checkpoint at meaningful state transitions and before yielding, not merely every 30 minutes. On resume, reconcile the saved project revision and active/unknown jobs with the real filesystem and process state. Do not carry approval grants across a restart; the owner reauthorizes the runtime. Never replay a filesystem write, command, or upstream MCP call solely because a response was lost.

Restart policy for the first implementation: graceful companion shutdown cancels bridge-owned running command groups, including explicitly started services. Managed containers may remain as reusable environments, but their bridge-owned commands do not intentionally survive a graceful shutdown. Never stop an attached container itself. After a crash, mark formerly active jobs `interrupted` or `outcome unknown`; recheck recorded OS/container execution identity without replay or automatic reattachment. After fresh owner authorization, recover/terminate only positively identified bridge-owned processes, otherwise surface manual recovery instructions. Saved task checkpoints survive; active execution is not promised to survive a restart. This is a proposed implementation choice, not an existing capability.

ChatGPT mode loads the same saved task when the owner says continue. A workflow skill requires checking unfinished steps and evidence, treating blocked work as blocked, and distinguishing partial progress from done. Skills alone cannot keep an ended model turn running or guarantee another prompt at a fixed interval.

Current OpenAI documentation also describes MCP Events: the user can subscribe in ChatGPT, the server sends signed events, and ChatGPT responds in the subscribed chat. Add optional event-driven resumption in the later plugin phase, conditional on the actual host/account supporting subscription. Events such as `task.checkpoint_ready` or `command.finished` signal meaningful changes, not a blind timer that repeatedly asks for continuation. Unsupported hosts retain the manual-resume path. Do not claim unlimited session duration or bypass platform limits.

The optional local agent uses the same task and tool services while the chat is idle. Proposed first backend: an OpenAI API agent with durable sessions, configurable model, step/time/cost budgets, cancellation, and bounded retry/backoff. Credentials and API usage are separate setup requirements; no API calls occur until the owner explicitly starts a configured run. The credential-free ChatGPT path remains usable. Alternative local agent backends can be added through the same runner interface later.

ChatGPT and the local runner must not mutate the project concurrently. Use a renewable task/workspace lease and serialized mutations. Read-only status can remain available. A handover releases or expires the old lease and reconciles work before the new worker starts. Pending human approval pauses dependent work instead of generating approval loops. Stop automatically on verified completion, explicit cancellation, exhausted budget, or repeated failure requiring input.

Persist event subscriptions/outbox separately from model state. Recheck subscriber authorization, validate and verify callback URLs, sign deliveries, deduplicate event IDs, retry transient delivery failures within limits, honor unsubscribe/revocation/expiry, and never include private source or credentials in event payloads. Do not emit unchanged periodic notifications.

## Organization and documentation

First preserve `source/` and the working public interfaces. Extract focused project-profile, Docker, integration-registry, task-store, and runner modules only as they acquire real responsibilities. Avoid a speculative framework or wholesale reformatting. Generated release folders remain generated; do not edit them independently.

Rename the eight owner-supplied illustrations descriptively under repository `docs/images/`, preserve their bytes, and provide an illustrated gallery plus README links. Their labels include example APIs and future capabilities, so captions must call out discrepancies. The self-contained source documentation remains text-based so packaging does not embed roughly 14 MB of illustrations into the hosted worker's setup-plugin payload.

Maintain README, setup, usage, troubleshooting, architecture, security, contributor, and tool references. Mark future work as proposed, with no version bump or claim that unsupported capabilities already exist. Include all text documentation needed by the portable-source package.

## Acceptance checks

- Approved host commands produce an observed artifact/output. A nonzero exit, missing executable, invalid work directory, denied/expired approval, timeout, and cancellation each return accurate terminal results. A queued command never appears as executed.
- Exercise Windows process startup and descendant cleanup. Preserve idempotency and revoked-workspace behavior. Reproduce the owner's original failing command through the real ChatGPT path before declaring that specific report fixed.
- Create, edit, move, read, and delete files/folders in a temporary project with explicit permissions. Competing edits, excluded files, path escapes, linked paths, and replaced roots remain protected.
- Run real Docker checks using a locally available approved image. Verify engine/image failures, managed and attached environments, shared workspace visibility, persistence across commands, file ownership, exact work directory, and cancellation ownership. No host fallback.
- Verify snapshot reconciliation including nested creates and deletions, unapplied/conflicting changes, and preservation of host changes after snapshot creation.
- Exercise local MCP discovery/calls/errors/restarts, selected skill loading, dependency reporting, namespacing, timeouts, and permission revocation. Do not imply an arbitrary installed application has an adapter.
- Restart and resume a task without losing its checkpoint or repeating side effects. Simulate lost responses, unknown process outcomes, competing workers, expired leases, approval pauses, and budget exhaustion.
- Prove the optional local runner resumes independently, stops on completion, and stays within its configured budgets. Check ChatGPT continuation manually and MCP Events only in a host where subscription is available.
- Run relevant Python/Node tests, build and artifact validation, portable-source/export link checks, image hash checks, and `git diff --check`. Keep credentials, runtime state, generated binaries, and unrelated owner files out of changes.

## Boundaries and unresolved evidence

No promise of unrestricted desktop control, perfect task completion, unlimited model sessions, or automatic installation of every integration. No deployment, publication, API spend, automatic image download, or changed sharing permissions without the relevant owner action. Existing private Site identity, database, keys, and transport are retained.

The original command and its observed local job result are still needed for exact end-to-end reproduction; the new diagnostic establishes a real outcome-reporting defect but not the cause of every reported no-effect command. The specific application adapters can be chosen once the generic integration layer is working. Platform-specific MCP Events availability must be checked on the user's actual ChatGPT installation.

## Official references reviewed

- [OpenAI: agent sessions and resumable state](https://developers.openai.com/api/docs/guides/agents/running-agents)
- [OpenAI: local and remote MCP configuration](https://learn.chatgpt.com/docs/extend/mcp)
- [OpenAI: authoring skills and tool dependencies](https://learn.chatgpt.com/docs/build-skills)
- [OpenAI: MCP Events and ChatGPT subscriptions](https://developers.openai.com/plugins/build/mcp-events)
- [Docker: running containers, mounts, exit codes, and resource limits](https://docs.docker.com/engine/containers/run/)
- [Docker: commands in existing running containers](https://docs.docker.com/reference/cli/docker/container/exec/)
