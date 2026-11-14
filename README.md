# ax

One prefix for ordinary commands, with a local daemon that keeps long work
supervised and connects context across Claude and Codex.

```sh
ax run -- python score.py
ax run --detach -- python score.py
ax detach TASK
ax attach TASK
```

Tasks are background-owned from creation. By default, `ax run` attaches normal
stdin/stdout/stderr and returns the command's exit status. Detaching closes the
connection while the same process continues; attaching again replays captured
output and resumes live stdio. Short commands finish without a model review.

The core provides conversation search, sourced topic handoffs, shared memories,
task supervision, numeric progress, usage and budgets. It has no built-in UI,
HTTP server, MCP server, Cloudflare tunnel or separate notification service.
Enforcement hooks and graphical consumers are separate from ax.

## Install

Requirements: Python 3.12+, `uv`, and installed, authenticated Claude/Codex CLIs
for the providers you use. ax uses Unix sockets and PTYs; the current validation
was performed on macOS. `zstandard` is the only Python runtime dependency.

From this checkout:

```sh
python3 scripts/install.py
ax --version
ax daemon status
```

The installer uses `uv`'s standard user tool directories and places `ax` in
`~/.local/bin`; that directory must be on `PATH`. When a C compiler (`cc`) is
available, it also builds the native command-prefix launcher. Otherwise, the
Python entry point remains available. The CLI starts its daemon on demand;
`daemon status` and `daemon stop` do not start one.

The small agent skill is included at [skills/ax/SKILL.md](skills/ax/SKILL.md).
For a new installation, link it into the provider's supported skills directory:

```sh
mkdir -p ~/.agents/skills ~/.claude/skills
ln -s "$PWD/skills/ax" ~/.agents/skills/ax
ln -s "$PWD/skills/ax" ~/.claude/skills/ax
```

Keep already-correct links in place. Reload the providers after installing or
replacing their skill. Installing ax does not add enforcement hooks.

## Commands and progress

`ax --help` and each command's `--help` describe the complete interface.
Data commands return JSON; `run` and `attach` carry the command's stdio.

```sh
# Conversation evidence and a model-written topic handoff
ax search "calibration" --project my-project
ax search "calibration" --provider claude
ax handoff "calibration decisions"
ax memory sync

# Existing or externally executed work
ax task watch "existing computation" --pid 12345
ax task create "remote annotation job"
ax task update TASK --done 20 --total 100 --unit videos --stage scoring
ax task update TASK --status done
ax task list
ax task list --all
ax task show TASK
ax task events TASK --after 42 --follow
ax task stop TASK

# Provider allowance, explicit spending and reservations
ax usage
ax usage --refresh
ax budget set annotations 20 --unit usd
ax budget reserve annotations 2
ax budget settle TICKET 1.50
ax budget release TICKET
ax budget add annotations 1
ax budget show
ax budget close annotations

# Local daemon
ax daemon start
ax daemon status
ax daemon stop
```

`run` infers caller identity, command, working directory and environment. The
command itself becomes the task purpose; `--description` adds context when
needed. Options precede `-- COMMAND ARGS`. To execute shell built-ins, pipelines
or redirections, pass the original command to a shell:

```sh
ax run -- sh -c 'printf hello | wc -c'
```

In a terminal, Ctrl+] detaches. Attached terminal commands receive a PTY and
terminal dimensions. Pipes retain distinct stdout/stderr and stdin. Ax-launched
work survives daemon restarts. Process identity is checked to avoid attributing
PID reuse to a task. `task stop` applies to an ax-launched live process.

Existing watched processes have an observed end, but ax cannot infer their exit
code. Externally reported work declares its own terminal state. A counter reaching
its total does not imply completion, and supervision continues while the task is
running.

`task events --follow` emits durable events followed by numeric snapshot ticks.
For example, a tick can contain these fields:

```json
{
  "type": "tick",
  "seq": 42,
  "at": 1794600000,
  "tasks": [
    {
      "id": "7f2c8a91b046",
      "status": "running",
      "done": 320,
      "total": 1000,
      "unit": "videos",
      "stage": "scoring"
    }
  ]
}
```

Ticks are emitted once per second. `seq` identifies the latest delivered durable
event and can be supplied through `--after` when reconnecting. Progress stays
separate from command output; a consumer chooses whether to render a number,
progress bar, chat card or widget.

## Mandatory supervision

By default, a registered running task receives its first inspection after
10 minutes, followed by an inspection every 10 minutes. `--every MINUTES` allows
10–60 minutes, with no disabled setting. At registration, it sets both the first
delay and subsequent interval; it can also be changed with `task update`.

Claude callers use Haiku; Codex callers use Luna. Both use low effort and the same
inspection prompt. Reviews examine the task purpose, elapsed time, recent
progress, previous inspections and a bounded output tail. Suspected stalls,
excessive duration, incorrect output or insufficient evidence raise a concern
with evidence and uncertainty to the original calling conversation. Failed
inspections also raise a concern. The reviewer leaves repairs, retries and
stopping to the calling agent.

Registration returns promptly; `run` attaches afterward unless `--detach` was
selected. The launch path does not wait for indexing, memory sync or a model
review. The search catalog uses a separate database so its writes do not block
task registration. The native launcher submits warm `run` requests directly,
then attaches the stdio client while the background worker starts.

Caller identity comes from `CLAUDE_CODE_SESSION_ID` or `CODEX_THREAD_ID`. Outside
an agent, or when the environment is ambiguous, supply an explicit identity:

```sh
ax --caller codex:SESSION_ID run -- python score.py
```

`AX_CALLER=provider:session` is also available when native identity variables are
absent. The identity must refer to the intended existing conversation for
escalation to reach it. Claude inbox credentials are captured privately from its
inherited environment; another ax command in that conversation refreshes the
binding. Codex escalation queues into and requests resumption of that same
conversation. No replacement conversation is created.

Delivery acceptance does not prove the caller has read or acted. Unavailable
routes retain pending concerns for retry. Uncertain dispatches are retained
without automatic replay to avoid duplicate actions. Their events remain visible
through `task events`; `daemon status` reports undelivered concern counts.

Provider model calls have a 90-second timeout and bounded input evidence. The
Haiku CLI receives a $0.15 per-call budget ceiling; Luna uses low effort and the
wall-time bound. Subscription usage is not converted into an invented dollar
cost. `handoff` uses the same provider routing and call bounds, and invokes a model
immediately. Ordinary monitoring does not invoke a model.

## Search, memory and accounting

Search uses local SQLite full-text indexing of both providers' main
conversations, including compressed Codex rollouts. It imports the existing ax
archive without modifying it. Results include excerpts, source paths and
conversation handles. Handoffs summarize bounded matching evidence with source
references; they do not transfer an entire provider conversation.

The daemon refreshes the catalog and shared memories every minute. Explicit
search refreshes before returning results. Memory sync preserves provenance,
tracks source deletions, and reports edited-import conflicts or unreadable notes.
Claude project notes are exported into Codex's ad-hoc notes, preferring
`memories_v2`. Codex shared notes and its generated summary are exposed through
an ax-owned index import in `~/.claude/CLAUDE.md`. Generated provider summaries
remain provider-owned. Imported notes are excluded from discovery to prevent
echo loops; provider consolidation and contextual recall remain provider behavior.

Budgets record explicit spending and reservations. A pending hold counts against
the cap; settling or releasing it updates available capacity. Existing ledgers
and reservations are preserved. Provider allowance windows are separate from
that ledger. Usage retains freshness information and labels unknown values.
Projections are estimates from observed pace, require adequate observations, and
respect allowance resets. Reported model usage/cost remains separate from
manually recorded budget entries.

## Switching Claude between VS Code and Desktop

The daemon keeps eligible local Claude conversations registered for both clients.
Every minute, it finds interactive CLI/VS Code conversations and adds missing
Desktop sidebar records while Desktop is **fully quit**. Desktop picks them up
on its next launch. VS Code already discovers the shared transcripts in their
project folders. Session IDs and transcript files stay the same; no conversation
content is copied, no app is opened and no model is called by registration sync.

Existing Desktop records, archives and deletion markers are preserved. Ax also
remembers registrations it has seen, so removing one does not cause it to be
recreated. Internal/background sessions, ambiguous IDs and unfamiliar metadata
are withheld. The signed-in CLI and Desktop account must match, and the Desktop
organization must be unambiguous. Check `ax daemon status` under
`conversation_sync` for pending registrations, reasons and errors. Codex keeps
using its shared native thread store.

From VS Code to Desktop, close the conversation's **editor tab**, allow the next
maintenance pass, then launch Desktop and select the conversation. For an
immediate native handoff, run this from an interactive terminal after closing
the editor tab:

```sh
claude --desktop --resume SESSION_ID
```

For the return trip, quit Claude Desktop completely, open the original project
folder in VS Code, and select the conversation from Claude's history. The
extension also accepts
`vscode://anthropic.claude-code/open?session=SESSION_ID`; verify the project and
session identity, because a missing session can produce a new conversation.
An ax command in the resumed Claude conversation refreshes the inbox binding
for its existing supervised tasks.

A local trial on November 14, 2026 with Claude Code / extension 2.1.325 and Desktop
5.11492.5 verified the same ID and latest displayed history across a full round
trip using completed synthetic messages and no model calls. It did not test a
model-generated continuation, attachments or artifacts. Choosing “New session”
retained idle writers in the sidebar workflows tested, and Desktop cached
previously viewed messages. This first version requires quitting Desktop before
continuing the conversation in VS Code; it never forces a client to close.

See the native [Desktop resume documentation](https://code.claude.com/docs/en/desktop#coming-from-the-cli)
and [VS Code URI documentation](https://code.claude.com/docs/en/vs-code#launch-a-vs-code-tab-from-other-tools).

## Local state and host access

State defaults to `~/.local/share/ax`. `AX_CONFIG` selects a TOML file with
optional `[paths]` entries for `data`, `claude_home`, `codex_home`, `claude_json`,
`claude_desktop` (the Claude app data directory), and the legacy `vault` location.
State includes the task/event database,
independent search catalog, captured task output, shared-memory notes and the
existing budget ledger. Historical archives and artifacts remain preserved.

The daemon is a trusted local executor: registered commands run with its host
permissions. A sandboxed agent host must authorize command execution and access
to the local socket; ax does not configure or relax host sandbox policy. The
current Codex sandbox requires that host-access wiring before ordinary sandboxed
tool calls can use the socket. Enforcement hooks belong to that separate layer.

`daemon stop` stops supervision and maintenance until restart. It does not
terminate registered work. Ax's only native-message delivery is task escalation
to its caller.

## Development and validation

```sh
uv sync --group dev
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run pytest
uv build
```

The current 72 deterministic tests cover both launchers, binary stdio, caller
environment and working directory, exit status, terminal input and dimensions,
detach/reattach without restarting the process, daemon recovery, supervision
policy, delivery state, memory conflicts, archive import, budget accounting and
add-only conversation registration with account, lifecycle and archive guards.
Model adapters use test doubles. Live model-backed Haiku/Luna supervision and
escalation were not exercised by that validation.
