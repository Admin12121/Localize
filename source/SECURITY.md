# Security

The hosted Site forwards requests; it cannot grant local permissions. The separate local control listener must remain on loopback and outside the tunnel. The local owner selects project scope, authorized CTF origins, write policy, command environment, and approvals.

Container execution uses a filtered project copy. Host execution runs with the user's OS account and may access beyond the project. It always needs exact local approval. Do not enable host mode or networking as a fallback.

Do not commit or publish `.runtime`, keys, OAuth PINs, tunnel logs, connection records, `.env`, `.dev.vars`, or workspace files. Use the sanitized source and release scripts.

Report vulnerabilities to the maintainer **admin12121** using the repository's private vulnerability reporting channel when enabled. Do not include live keys or private project contents in public issues. No security audit or response-time guarantee is claimed.
