# Security

The private Site authenticates its user and forwards requests; it cannot grant local permissions. Only authenticated RPC belongs behind the tunnel. The separate local control listener must stay on loopback.

## Local authority

The owner selects the project, approved web origins, command environment, optional integrations and grants. Host jobs always require exact local approval. Text edits, folder operations, recursive deletion, container commands and networking have distinct local policies. Saving permissions or pausing revokes current access/pending work without undoing applied effects. Restart requires new grants.

Workspace tools enforce relative paths, sensitive exclusions, link rejection, hashes and content limits. Those restrictions do not sandbox host commands: they use OS-account authority, can access beyond the project, use networking and modify files without proposal previews. Never silently fall back to host execution.

Snapshot containers receive a filtered copy; networking is separately enabled. Live Docker shares the real selected project, including files excluded from file tools/snapshots, and approved commands can mutate it directly. Its context/endpoint and mount are validated; Docker socket exposure is rejected. Existing-container broader access needs local inspection and acknowledgment where applicable. Only bridge-owned containers can be stopped/removed through the bridge's controls. Cancellation targets owned command processes but cannot roll back prior side effects.

Approved-target HTTP/browser networking is scoped to exact locally approved origins; private lab targets need explicit local opt-in. Redirects are not followed. Browser and HTTP sessions are separate. These target controls do not constrain host-command or configured adapter networking.

## Skills, adapters and the local agent

Skill instructions, repository text, tool descriptions and command output are untrusted workflow data, not permission grants. Selecting a skill does not install tools or authorize arbitrary application access. Trusted stdio/HTTP MCP adapters may have authority beyond workspace files; configure only required tools and credentials. Empty allowlists expose nothing. Tool schemas are validated, configured credentials are redacted from exposed state/results, and interrupted calls are not automatically retried because they may already have mutated an application.

The optional local agent needs an explicit model, API-key environment-variable **name**, local enable/start actions and step/time/token budgets. It uses the same grants and writer coordination; host approval is still per command. API usage is separately billed and budgets do not guarantee a fixed cost. Saving configuration alone makes no API call. This build does not enable automatic ChatGPT event prompts.

## Credentials, private data and recovery

Never commit or publish runtime folders, connection keys, local control codes, OAuth PINs, tunnel logs, connection records, `.env`, `.dev.vars`, selected project data or API credentials. Use sanitized source/release scripts. Preserve an existing private deployment's identity, encryption secret, database and sharing during upgrades; a new owner needs their own deployment and secrets.

Saved tasks, evidence, MCP configuration, retained snapshots, recoverable deletion trash and text-write recovery backups can contain private source. Keep credentials out of task handoff/output. The runtime's integration configuration may intentionally contain local adapter secrets even though model-visible responses redact them. File filters are not a comprehensive secret scanner.

Recoverable deletion preserves local content rather than securely erasing it. Preserve its runtime records for restore. A reported POSIX `recovery_path` retains the original inode, including potential writes through another process's existing descriptor; inspect it locally before cleanup. Conflict recovery is not permission to overwrite a competing destination.

## Interpreting results

Approval and transport success do not prove execution or task completion. In 3.2, nonzero command exit is failure; timeout/cancellation are distinct. Check `success`, exit/output/launch evidence and `cleanup_pending`, then verify the intended effect. Snapshot reconciliation can be partial despite a successful process exit. Tasks record evidence, do not replay uncertain mutations, and require configured acceptance checks for machine verification. External editors are outside the bridge's writer lease.

Conceptual illustrations and dated designs do not expand permissions or promise enabled features. macOS native file-operation paths still require platform execution verification; no independent security audit is claimed.

## Report a vulnerability

Contact maintainer **admin12121** through the repository's private vulnerability reporting channel when enabled. Do not put live keys, private project contents or identifying logs into public issues. No security-audit or response-time guarantee is claimed.
