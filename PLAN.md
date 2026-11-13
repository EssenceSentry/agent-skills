# ax scope

The implemented surface is search, handoff, memory sync, supervised tasks, usage,
budgets and a local daemon. Supervision is mandatory, defaults to 10 minutes and
allows 10–60 minutes; Claude uses Haiku, Codex uses Luna, both with low effort.
One shared prompt inspects progress and output and raises concerns to the caller.
There is no built-in UI, HTTP service, Cloudflare, user notification service,
generic peer messaging, full-history transfer or enforcement-hook management.

Existing archive and budget data are retained. Enforcement hooks and visual
consumers are explicitly outside this repository's implementation scope.
