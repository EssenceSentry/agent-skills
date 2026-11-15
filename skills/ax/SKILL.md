---
name: ax
description: Search Claude/Codex conversations, prepare topic handoffs, sync memories, run supervised commands, inspect usage or budgets, and subscribe to usage alarms with the local ax CLI.
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
- Usage alarms: `ax usage watch codex:primary --at 80` (or a Claude window from `ax usage`). Wake at reset: `ax usage watch claude:five_hour --reset` (or `weekly_all`, `codex:primary`/`secondary`). List/cancel: `ax usage watches`, `ax usage unwatch ID`.

Caller identity is automatic. Running tasks receive mandatory Haiku/Claude or Luna/Codex supervision at low effort every 10 minutes (`--every` permits 10–60). Concerns reach the original conversation. Short commands finish without model calls; handoffs invoke a model immediately. Data commands return JSON. Enforcement hooks are separate.

The daemon registers eligible Claude conversations while Desktop is closed. Switch from a closed VS Code editor tab; quit Desktop before continuing in VS Code.

Thresholds use fresh percentages; reset wakes use saved provider deadlines, even while the caller is idle. Subscriptions fire once per window and learn the next reset from fresh data. Unknown reset times wait; wake-ups require a fresh availability check before resuming work. Delivery automatically steers/resumes the caller through its live native client. Without a compatible Codex Desktop/VS Code owner it stays pending; queued items alone are not delivery.
