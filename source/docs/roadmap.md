# Proposed upgrade direction

[Documentation index](index.md) · [Full design for review](superpowers/specs/2026-10-26-web-bridge-upgrade-design.md)

**Status: proposed.** This documentation does not add runtime features or change version 3.1.1. Upgrade the project and verify it first; update the installed plugin afterward.

## Stages

1. **Reliable commands:** distinguish approval, process launch, success, failure, timeout, cancellation and verified task results. Retain actionable diagnostics and incremental output. Remove the need to restart just because 30 jobs have accumulated.
2. **Complete project work:** add scoped folder/file creation, rename/move and deletion with conflicts, recovery and explicit local permission policy. Use the same project for file tools and commands.
3. **Understandable Docker setup:** show engine/image/container readiness, prepare an explicitly selected environment, create a persistent project container or attach a validated existing one, and show the project mount and command environment clearly.
4. **Selected local integrations:** discover and load trusted skills, connect selected stdio/HTTP MCP servers, and expose configured application adapters. A skill's instructions do not automatically provide its required tools or application access.
5. **Durable work in both modes:** save task steps, evidence, checkpoints, remaining work and blockers. ChatGPT resumes the saved task; an optional local agent can continue independently with configured budgets and cancellation. Serialize mutations so both do not change a project at the same time.
6. **Plugin release:** update contracts and workflow skills, test the whole connection, then update the existing installed plugin without changing ownership, credentials or sharing.

## Can a skill automatically continue every 30 minutes?

A skill can require checkpointing, result verification and an accurate handoff. It cannot, by itself, keep a stopped model running, guarantee another prompt, or bypass platform limits. Checkpoints should follow completed steps and side effects rather than rely on one fixed interval. [OpenAI skill documentation](https://learn.chatgpt.com/docs/build-skills) describes skills as instructions, resources and optional scripts.

For the ChatGPT path, preserve the task and resume on the next prompt. Current OpenAI documentation also describes [MCP Events](https://developers.openai.com/plugins/build/mcp-events): after a user subscribes, server events can cause ChatGPT to respond in that chat. This offers a supported path for event-driven continuation where the actual host/account supports it; this repository does not implement it yet, and it is not a promise of unlimited execution.

For independent continuation, the proposed optional local runner uses durable state, retries, stop conditions and explicit time/step/cost budgets. A first OpenAI API backend needs separate credentials/setup and can incur API charges when started; ChatGPT mode remains usable without that backend. [OpenAI agent sessions](https://developers.openai.com/api/docs/guides/agents/running-agents) provide a documented basis for resumable state.

Neither path should report done merely because a command was accepted or time elapsed. Completion requires the task's acceptance checks; blocked, interrupted and partially finished work must remain visible.
