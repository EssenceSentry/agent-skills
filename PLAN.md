# ax scope

The implemented surface is search, handoff, memory sync, supervised tasks, usage,
budgets and a local daemon. Supervision is mandatory, defaults to 10 minutes and
allows 10–60 minutes; Claude uses Haiku, Codex uses Luna, both with low effort.
One shared prompt inspects progress and output and raises concerns to the caller.
There is no built-in UI, HTTP service, Cloudflare, user notification service,
generic peer messaging, full-history transfer or enforcement-hook management.

Existing archive and budget data are retained. Enforcement hooks and visual
consumers are explicitly outside this repository's implementation scope.

Claude client registration is automatic maintenance with an unchanged CLI. It adds missing Desktop records only while Desktop is quit, preserves native IDs/transcripts and client records, and leaves Codex native registration alone.

Usage alarms are opt-in subscriptions under `ax usage`: fresh observed percentage thresholds, one automatically delivered native message per allowance window (reset jitter tolerated) to the requesting caller, reset re-arming, and cancellation. Threshold checks invoke no model and add no external notification service.

Reset wakes share `usage watch --reset`, listing, cancellation and native delivery. Fresh provider data arms persisted reset deadlines; daemon ticks fire them without fresh usage or model calls. Future deadlines are learned from evidence, not fixed-period guesses.
