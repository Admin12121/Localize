# Progress: Web-Bridge 3.2.0 upgrade

All code and documentation are in the explicitly requested existing checkout. The user approved the design and implementation. No commits, index changes or live publication were performed by the agents.

- Commands: outcomes, evidence, explicit shells/Windows quoting, timeout, incremental output, rolling history, durable SQLite receipts, inspection-only interrupted recovery and recovery write blockers implemented.
- Files: nested create, mkdir, move, recoverable delete/restore, bounded recursive previews, Windows source pin/no-replace publication and POSIX recovery backups implemented.
- Docker: locally pinned context, explicit image preparation, persistent managed projects, validated mapped attachment, owned-only lifecycle and exec-group cancellation implemented.
- Integrations: selected skill roots/bundled workflow and optional stdio/HTTP MCP adapters, allowlists, schema checks, bounded calls, credential redaction and no automatic SDK replay implemented.
- Tasks/runner: SQLite checkpoints, acceptance verification/manual local review, same-root local rebind, dead-process lease recovery, heartbeat, metadata-independent replay prevention, inspectable operation records and explicit budgeted optional runner implemented.
- Controls/contracts: owner-only setup and recovery routes, local forms, 27 tool schemas, worker instructions and source metadata 3.2.0 implemented. Status polls use compact SQL summaries rather than full command/task documents.
- Docs/images: all eight image hashes preserved, renamed gallery and current guides updated.
- Review: independent reviewers reproduced important findings; all were fixed with regressions. The last Docker cleanup fix was independently re-reviewed: 5 focused tests passed, no remaining important findings within the reviewed scope.
- Final verification: Windows complete suite **143 passed, 4 skipped** (68.19s), with opt-in real Docker checks. Linux selected filesystem/task/command/recovery suite **91 passed, 13 skipped** (14.21s). Gateway/control panel suite **16 passed**. Build, ESM validation, release packaging and sanitized source export passed. Documentation verification: **86 local links, 13 JSON examples, 8 unchanged image hashes, 27 tools**.
- Skips/limits: optional Playwright browser dependency is absent; OS-specific tests skip on the other OS. The Linux offline run did not install MCP/OpenAI SDKs or run nested Docker. Optional SDK fixtures and real Docker checks passed in the Windows suite. No paid API call, real third-party app action or macOS hardware verification.
- Delivery: local bridge **3.2.0**, setup-plugin package **1.2.0**. Root distributions rebuilt from curated archives; no runtime/config directories removed. No live publication.

Rulings: preserve successful legacy state `completed` and add explicit success flag; no inferred host fallback; retain ambiguous effects instead of replay; keep prior-session receipts local-only; no automatic model-session extension; leave live Site/plugin publication for a separate owner deployment step. macOS native filesystem path is implemented from official API documentation but not verified on hardware. No paid model call or real third-party app adapter was invoked.
