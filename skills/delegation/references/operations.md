# Operations and compatibility

## Authentication

Inspect `claude --version`, `claude --help` and `claude auth status`. Avoid printing account identifiers or credential material. The runner checks subscription authentication without exposing those details. The reference environment used **2.1.283** on 2026-09-27; inspect the actual installation and account before relying on that compatibility snapshot.

Keychain restrictions can make authentication look absent. Use approved host execution when authorized; don't extract tokens. No new API key is needed. `--bare` skips OAuth/Keychain, so is unsuitable here. The runner rejects non-subscription authentication rather than silently using API billing.

Safe mode retains normal authentication, permissions, built-in tools and admin policy; it disables local customizations. Carry applicable user/repository instructions in the brief. Safe mode isn't an OS sandbox.

## Actual usage and freshness

Live-tested on 2.1.220:

```sh
claude -p /usage --safe-mode --tools '' --permission-mode dontAsk \
  --output-format json --no-session-persistence
```

This invokes built-in usage with zero model turns and reported inference cost, returns the three bars as text, and refreshes `cachedUsageUtilization` in the global config. It was reverified on 2.1.283. It works without completing interactive onboarding. Don't change onboarding flags or accept terms just to read quota. This observation doesn't establish that every future CLI build has no incidental background usage.

`usage.py` validates the zero-inference result and normalizes the cache. Default: `~/.claude.json`. For a custom `CLAUDE_CONFIG_DIR`, supply `--config` with the actual global JSON path. The helper reads only quota data, never prints other config contents or the account UUID.

Observed schema: `fetchedAtMs` timestamps the snapshot. `utilization.limits` contains session, overall-weekly and model-scoped weekly rows. Fable is recognized by the scoped model display name or ID, not an internal codename. Legacy `five_hour`/`seven_day` fields are supported. Unknown schemas produce unknown values.

Remaining = 100 minus used percentage, with zero remaining when usage exceeds 100%. Retain reset timestamps and countdowns. Missing, null, negative and non-finite fields remain unknown; duplicate matching rows are marked ambiguous rather than silently choosing one. Stale or reset-expired snapshots have no `current_remaining_percent`, while historical values remain visible. Default freshness is five minutes, but `refresh_verified` additionally requires successful CLI execution and a new cache timestamp. CLI success alone doesn't prove network refresh.

Exit 0 means all three windows met requested freshness; exit 2 means unavailable data/freshness. If only Fable is absent, non-Fable work can still be considered using valid overall windows. Inspect `cli_window_summary` if cache parsing fails, but don't claim text is fresh without evidence. Missing Fable data doesn't imply free usage.

On failure, report age/reason, use `/usage` interactively or the authenticated [usage settings page](https://claude.ai/settings/usage) if appropriate, and continue independent parent work. Don't continuously poll or call private endpoints with extracted OAuth tokens.

Fable is separately tracked but also uses the overall weekly allowance on eligible included plans. A large Fable balance doesn't bypass an exhausted week. Entitlement depends on seat/plan; `subscriptionType: team` alone doesn't prove premium access. [Fable plan rules](https://support.claude.com/en/articles/15424964-claude-fable-models-on-your-plan).

## Worker lifecycle and artifacts

`worker.py run` stays foreground under the host's asynchronous process tool. It emits start, 30-second progress and completion records. It saves:

| File | Purpose |
| --- | --- |
| `brief.md` | Submitted task |
| `run.json` | State, heartbeat, session/model IDs, recent activity, denials and estimates |
| `events.jsonl` | Streamed tool/result events |
| `stderr.log` | Failure diagnostics |
| `result.json`, `answer.md` | Final result and answer, when returned |
| `session.lock` | Serializes resumes of one conversation |
| `stop.request` | Cancellation request for the owning runner |

Read compact status before detailed logs. Private run directories can contain task data; don't publish/commit them by default.

`status` sends no prompt. `stop` writes a request; the runner terminates its own process group and records `stopped`. Timeout works similarly. Never signal a PID taken from the user's session inventory. Confirm process exit before cleanup. A hard-killed runner can leave an orphan: verify ownership through the original host handle and command before manual cleanup.

Follow up with `run --resume-run <latest-run>` after its process exits, in a new run directory. A lineage lock prevents concurrent resumes. Don't resume an older turn: costs/context include later turns. For independent review, start a new session and avoid providing the original conclusion as the desired answer.

`--max-cost-usd` maps to CLI `--max-budget-usd`, a budget for the new invocation. Restored costs from earlier runs do not consume it. Result totals can include prior conversation costs; do not sum them. Subscription charges and quota conversion differ. Missing results don't mean zero cost. The helper computes incremental cost only when comparable cumulative values exist. Enforcement can occur between requests, so a request may cross an estimate budget.

Live check on 2.1.283: an Opus review reported a $0.2290968 estimate; its short follow-up used a new $0.10 budget and succeeded with a $0.2877448 conversation total. The marker from the initial task was recovered without being repeated in the follow-up prompt. This verifies both continuation and the distinction between per-invocation budgets and cumulative results. These are CLI estimates, not a subscription bill. The worker requires 2.1.283+ rather than assuming identical reporting on older builds, and leaves incremental cost unknown across CLI-version changes.

## Tool permissions and failures

The runner combines `--tools`, explicit `--allowedTools`, `dontAsk` and safe mode. This is not a filesystem jail. `edit` permits built-in writes; Bash requires a command rule. Inspect commands and their indirect effects before granting them. Respect parent authorization and host sandbox boundaries.

Permission denials become `needs_review`. Fix the brief/scope or allow only the required, authorized action; don't enable all tools. On rate limits, refresh usage, reduce concurrency and use bounded backoff. Don't repeatedly retry exhausted allowances or change to paid credits. For poor outputs, improve the brief or escalate capability, then verify.

Recursive Agent/Task tools and arbitrary MCP tools are excluded. More complex SDK steering is possible as a separate workflow when needed; it is not required for independent batches.

## Version distinctions

Installed help controls availability. The live Opus 5.5 test on 2.1.220 was rejected with a requirement for **2.1.280 or newer**; the runner detects this before dispatch. In 2.1.220, `claude agents --json` inventories sessions; `--all` includes completed background sessions. `agents` has options, not a `send` subcommand. Don't invent `claude agents send` or assume a newer `claude attach` exists without inspecting installed help.

Native background sessions (`--bg`) and interactive teams are separate mechanisms. This runner uses `-p` and exact resume IDs; it doesn't claim live-turn messaging or native Codex mailbox semantics. Avoid `--continue`, which can select an unrelated recent conversation.

Direct `AGENTS.md` discovery requires 2.1.277 according to current docs. Tested 2.1.220 predates it. Existing `CLAUDE.md` imports of `@AGENTS.md` can remain, but this runner disables all such auto-discovery. Supply actual applicable rules in the brief instead of modifying repositories or assuming discovery.

## Primary operational sources

- [Noninteractive execution and result streams](https://code.claude.com/docs/en/headless)
- [CLI reference](https://code.claude.com/docs/en/cli-reference)
- [Usage and cost interpretation](https://code.claude.com/docs/en/costs)
- [Instruction discovery and version requirements](https://code.claude.com/docs/en/memory)
- [Subagents](https://code.claude.com/docs/en/sub-agents)
- [Interactive agent teams](https://code.claude.com/docs/en/agent-teams)

Headless `/usage` and its cache adapter were established by local execution, not inferred from the newest documentation. Re-test after incompatible updates rather than fabricating fresh readings.
