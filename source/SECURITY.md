# Security

The hosted Site forwards requests; it cannot grant local permissions. The separate local control listener must remain on loopback and outside the tunnel. The local owner selects project scope, authorized CTF origins, write policy, command environment, and approvals.

Container execution uses a filtered project copy. Host execution runs with the user's OS account and may access beyond the project. It always needs exact local approval. Do not enable host mode or networking as a fallback.

Do not commit or publish `.runtime`, keys, OAuth PINs, tunnel logs, connection records, `.env`, `.dev.vars`, or workspace files. Use the sanitized source and release scripts.

Report vulnerabilities to the maintainer **admin12121** using the repository's private vulnerability reporting channel when enabled. Do not include live keys or private project contents in public issues. No security audit or response-time guarantee is claimed.

## Interpreting operation results

Permission approval and transport success are separate from process success. In 3.1.1, a job can be marked `completed` with a nonzero exit code. Check exit code and actual output/effect before relying on a result. Docker snapshot changes may still require approval, conflict with host changes, or be unsupported; a successful container process does not establish that the original project was updated.

Supplied architecture illustrations include conceptual APIs and future features. Their labels do not expand filesystem, Docker, host, browser or application permissions. Existing-container attachment, local MCP integrations and autonomous task continuation are not implemented in 3.1.1. Any future implementation must preserve locally selected authority and keep credentials out of model-visible configuration and task logs.
