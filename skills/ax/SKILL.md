---
name: ax
description: Search Claude/Codex conversations, prepare topic handoffs, sync memories, run supervised commands, and inspect usage or budgets with the local ax CLI.
---

# ax

Use `ax --help` for the complete interface.

- Run commands: `ax run -- COMMAND ARGS`. Normal stdio and exit status; the process is background-owned.
- Disconnect/reconnect: `--detach`, `ax detach ID`, `ax attach ID`.
- Find history: `ax search "topic"`; use returned evidence and source paths.
- Prepare a sourced, inexpensive summary: `ax handoff "topic"`.
- Sync memories: `ax memory sync`.
- External work, numeric progress and event streams: `ax task --help`.
- Allowances/projections: `ax usage`; spending/reservations: `ax budget --help`.

Caller identity is automatic. Running tasks receive mandatory Haiku/Claude or Luna/Codex supervision at low effort every 10 minutes (`--every` permits 10–60). Concerns reach the original conversation. Short commands finish without model calls; handoffs invoke a model immediately. Data commands return JSON. Enforcement hooks are separate.

The daemon registers eligible Claude conversations while Desktop is closed. Switch from a closed VS Code editor tab; quit Desktop before continuing in VS Code.
