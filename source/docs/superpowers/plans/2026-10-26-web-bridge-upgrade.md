# Web-Bridge Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Independent new modules may use superpowers:dispatching-parallel-agents with exclusive file ownership; the main agent owns integration and whole-change verification.

**Goal:** Implement the approved reliable local-project bridge, Docker setup, selected local integrations and durable work continuation before any installed-plugin publication.

**Architecture:** Keep Python companion authority and the existing Site gateway. Separate command launch, scoped file mutations, Docker project setup, trusted integrations and durable task/runner state into focused modules. Bind every capability to local configuration and current workspace identity.

**Tech Stack:** Python 3.10+, standard library core; optional maintained `mcp` and `openai` Python SDKs; existing Node.js worker/build/test tooling.

**Spec:** `source/docs/superpowers/specs/2026-10-26-web-bridge-upgrade-design.md` (approved 2026-10-26).

## Global Constraints

- Work directly in `C:\Dev\admin12121\@26\Web Bridge`, as explicitly requested. Preserve existing documentation/images and staging boundaries; do not commit/push/publish.
- Core companion remains runnable without pip; optional integrations/agent dependencies must fail with clear setup guidance when absent.
- Credentials, runtime data and task state stay local and out of source/releases. Do not invoke paid APIs or download images merely by configuring them.
- Host exact-command approval remains default. Profile mismatch cannot silently switch execution environment. No tool grants itself access.
- Existing private Site identity, keys, database, sharing and tunnel transport remain unchanged.

## Review Focus

- Windows shell built-ins, npm batch wrappers, spaces and failed native commands must launch explicitly and preserve failure status.
- File mutations must preserve competing user edits and reject path escapes/linked paths, including new nested folders and deletion recovery.
- Attached containers must map the selected project and must never be removed or globally killed by bridge cancellation.
- A resumed task must not replay uncertain side effects; competing chat/agent mutations must not run concurrently.
- Local MCP discovery/calls and model output are untrusted; only locally selected servers/tools and current grants may execute.

### Task 1: Command execution and lifecycle

**Files:** `bridge/server/jobs.py`, new `bridge/server/command_launch.py`, `bridge/tests/test_execution_upgrade.py`.
**Interfaces:** `launch_command(argv=None, command=None, shell=None, environment='host') -> list[str]`; Jobs accepts existing argv and a normalized explicit shell launch from Companion. Preserve legacy successful `completed` with explicit `success:true`; failed exits become `failed`, timeout `timed_out`, with timestamps/execution evidence/output cursors.

- [ ] Write/run failing tests for nonzero exits, explicit PowerShell/cmd npm, timeout distinction, output offsets and history rotation.
- [ ] Implement strict mutually exclusive argv/shell command inputs, configured timeout ceiling, diagnostics and per-job lifecycle evidence. Preserve idempotency and exact approval.
- [ ] Run new tests and existing companion/cancellation tests. Record results in progress ledger.

### Task 2: Scoped filesystem lifecycle

**Files:** `bridge/server/workspace.py`, new `bridge/server/file_operations.py`, `bridge/tests/test_file_operations.py`.
**Interfaces:** `FileOperations(workspace, runtime).propose(operation,path,destination=None,expected_sha256=None,recursive=False)`, `.apply(operation_id)` and `.preview(operation_id)`; create-directory, move, recoverable delete; text create/edit keep Workspace interface.

- [ ] Prove missing-directory creation, move/delete hash conflicts, trash recovery, traversal and linked-path rejection with failing tests.
- [ ] Implement descriptor/Windows-handle-safe operations and approvals, supporting nested text-file creation. Bind pending operations to workspace generation and local write policy.
- [ ] Verify real temporary-tree effects and existing workspace hardening tests.

### Task 3: Docker project service (independent module)

**Files:** new `bridge/server/docker_project.py`, `bridge/tests/test_docker_project.py`.
**Interfaces:** `DockerProject(runtime)`, `.status()`, `.configure(config, workspace)`, `.action(action,workspace,**args)`, `.build_command(job_id,argv,cwd)->list[str]`, `.cancel(job_id)`; config is selected locally, execution consumes saved validated configuration.

- [ ] Test context consistency, readiness errors, mount validation, unowned-container preservation and project workspace visibility before implementing.
- [ ] Implement explicit local context/image checks, pull/create/attach actions, persistent managed project container, attachment only with matching host bind mount, owned exec cancellation, owner-only stop/remove.
- [ ] Use existing local node image for real temporary-project roundtrip and cancellation checks. Never download images automatically.

### Task 4: Selected skills and MCP services (independent module)

**Files:** new `bridge/server/integrations.py`, `bridge/tests/test_integrations.py`, `bridge/requirements-integrations.txt`.
**Interfaces:** `Integrations(runtime)`, `.configure(entries)`, `.status()`, `.skills()`, `.skill_read(name,resource='SKILL.md')`, `.tools(server=None)`, `.call(server,tool,arguments)`; registry changes local-only, read/call still require current companion grants.

- [ ] Test trusted-root boundaries, disabled/unlisted tools, missing dependencies, stdio/HTTP fixture discovery and real calls.
- [ ] Implement skill/resource access, optional maintained MCP SDK client, configured server/tool allowlists, timeouts, bounded responses, safe errors and local credentials.
- [ ] Verify the real fixture and document optional installation; no arbitrary app-control claim without a configured MCP adapter.

### Task 5: Durable tasks and optional runner (independent module)

**Files:** new `bridge/server/task_store.py`, `bridge/server/agent_runner.py`, `bridge/tests/test_task_store.py`, `bridge/tests/test_agent_runner.py`.
**Interfaces:** `TaskStore(runtime)` with `.create(intent,checks,workspace)`, `.list()`, `.read(id)`, `.checkpoint(id,...)`, `.claim(id,owner,ttl)`, `.release(id,owner)`, `.cancel(id)`; `AgentRunner(store, execute, verify)` with local start/cancel/status/configure and optional OpenAI Responses backend.

- [ ] Test restart persistence, interrupted jobs/no replay, lease contention/expiry, checkpoints and cancellation before implementation.
- [ ] Implement SQLite records, handoff and finite bounded runner; optional OpenAI key/model setup, no calls until local start, bounded steps/time/tokens, pending-approval pause, no fabricated completion without verifier evidence.
- [ ] Verify with an injected fixture model/executor, no paid API calls. Add a project workflow skill for checkpoint/resume/verification; automatic ChatGPT events remain host-capability-dependent and must be reported accurately.

### Task 6: Companion, local controls and contracts

**Files:** `bridge/server/companion.py`, `control.py`, `bridge.py`, `bridge/control.html`, `bridge/BRIDGE_TOOLS.json`, `worker/runtime.js`, build scripts and tests.
**Interfaces:** current workspace-bound APIs plus explicit shell fields, filesystem operations, Docker status, selected skill/MCP tools and task/checkpoint tools. Owner-only control routes configure profiles/Docker/registry/runner. Mutation lease prevents concurrent chat/local-agent writes. Preserve schemas as single source of truth.

- [ ] Add integration tests for configured host/Docker default, rejected conflicting environment, local-only grants, all new tool schemas and RPC error flags.
- [ ] Wire new modules, useful error messages and local UI forms/actions. Preserve existing auth/origin/CSRF and CTF behavior. Update tool counts in tests to assert actual contracts, not old constant counts.
- [ ] Run Python suite, Node suite, real host command matrix, real Docker roundtrip, build and artifact validation. Include new source files/dependencies/skill in curated packaging.

### Task 7: Documentation, release artifacts and final review

**Files:** root/source READMEs, setup/usage/troubleshooting/architecture/security, metadata, tests, generated release outputs.

- [ ] Update docs/version/capability tables to implemented behavior, retaining explicit limits and unverified host-specific behavior.
- [ ] Build release artifacts locally, verify sanitized archive contents and documentation links, preserve image hashes and unrelated work.
- [ ] Dispatch a fresh reviewer of the complete change; fix important findings with regressions, rerun relevant checks and record final results.
- [ ] Deliver reviewable source and local artifacts. Do not publish/update an account plugin or call paid services without its explicit start/deployment step.

## Progress and rulings

Progress is recorded in `source/docs/superpowers/plans/2026-10-26-web-bridge-upgrade-progress.md`. The user's “go ahead” authorizes implementation of the reviewed design; another implementation-plan approval is unnecessary. In-place execution was explicitly requested. Independent agents own only the new Docker, integration, and task/runner modules; the main agent owns shared code, tests and integration. The tests/dependency environment lives in the chat workspace, outside the selected project. No commits are required for this run.
