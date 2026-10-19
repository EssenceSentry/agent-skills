# Codex native agents and CLI delegation

Use this route when the task calls for Codex. Preserve the requested provider,
model and reasoning. Existing Claude helpers and allowance readers are not
Codex helpers; This skill's Codex CLI helper uses the signed-in ChatGPT account, independent of Claude's
five-hour window. Both still share task cloud, storage and authorization limits.

## Choose the execution surface

- Native collaboration tools suit subtasks of the current chat. They inherit
  its context and execution policy. Keep the parent free to return while workers
  run when the client supports that lifecycle.
- Direct CLI workers suit explicitly authorized separate local sessions,
  durable external workers, or a user-selected alternative when native slots are
  occupied. A separate CLI session has its own context; provide the actual
  repository instructions, inputs, ownership and acceptance criteria.
- A CLI coordinator with native children is possible only when that workflow
  and recursion are authorized and its current client exposes the tools. The
  supplied helper defaults to independent workers with recursion disabled.

Do not silently replace Claude with Codex, create user-owned app chats as a
subagent mechanism, weaken sandbox/approval policy, or use external processes to
evade an organizational restriction. A user-authorized separate CLI session is
a distinct execution route; it does not grant new cloud, data or account access.

### Desktop app tools are a separate capability

The desktop can expose native tools for reading and messaging ChatGPT chats.
Prefer them for an approved existing Pro conversation; an external CLI worker
is not needed to forward that question. Their availability in this app session
does not establish availability in an independent CLI process.

`codex app` launches the desktop app. The app-server protocol supports direct
MCP tool calls, but it still needs access to the configured server. In the
2026-10-19 macOS probes, both a standalone MCP client and the bundled CLI's
app-server route were rejected by the desktop bridge with
`untrusted-code-signing-identity`. This is an observed installation boundary,
not proof that all future clients or platforms lack a supported route. Do not
disable the check, extract credentials, or launch an additional agent merely
to retry it. See [ChatGPT app tools](chatgpt-app-tools.md) for the support matrix,
history export limits, and distinction between native messaging and browser setup.

## Establish the runtime before launch

1. Inspect the exact binary's `--version`, `exec --help`, `exec resume --help`
   and `login status`. A PATH CLI may be older than the app's bundled CLI. On
   macOS, a verified current installation exposed
   `/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex`; discover
   the actual app path rather than assuming this path everywhere.
2. Require the intended subscription login. `Logged in using ChatGPT` confirms
   that login route, not model entitlement or cloud permissions. The helper
   removes model API keys/base-URL overrides and pins the first-party provider;
   it never switches to API billing. Do not read or print `auth.json` secrets.
3. Determine the parent's effective model from its current session metadata,
   not the user config default. Verify `turn_context.payload.model` and `effort`
   on the exact owned transcript. In one real case, config default Astra differed
   from the running GPT-6.1 Sol parent. Pin the explicit requested model with
   `-m` and effort with `-c model_reasoning_effort='"high"'` (or requested Ultra).
   Do not silently lower effort if the client rejects it.
4. If incompatible, use a verified compatible bundled binary or update through
   `codex update` when authorized. An older CLI's config-parser rejection of
   `ultra` is not evidence that login expired. A command-only lower-effort
   override may allow that updater to run; it must not change worker selection.
   An already running pinned binary need not be restarted after a PATH update.

Use current official [CLI documentation](https://learn.chatgpt.com/docs/developer-commands),
[subagent settings](https://learn.chatgpt.com/docs/agent-configuration/subagents#global-settings)
and the current binary's help for version-sensitive flags. Configuring
`agents.max_concurrent_threads_per_session` (legacy `agents.max_threads`) does
not prove an already running session accepted extra slots. Test actual admission;
do not kill useful workers merely to refresh settings.

## Launch and verify

`scripts/codex_worker.py` is standard-library Python3.10+ for POSIX. It runs in
the foreground; detach it with the host's authorized asynchronous process tool
when work must survive the parent turn. Use a fresh invocation directory.

```bash
python3 scripts/codex_worker.py run \
  --codex /verified/path/to/codex \
  --cwd /authorized/workspace \
  --brief /authorized/task.md \
  --run-dir /authorized/runs/worker-01 \
  --model gpt-6.1-sol --effort high \
  --permission auto-review --timeout 3600
```

The model in this example is not a default; supply the task's actual selected
model. Use High only when selected or permitted. Ultra is supported by compatible
clients/models; it is not necessary for every worker.

The helper uses `codex exec --json`, stdin for the brief,
`-o answer.md`, recursion disabled and the specified working root. Automatic
review uses `--approve-for-me`; read-only pins `-a never`, `-s read-only` and
`approvals_reviewer="user"` for that invocation. A verified client rewrote
`never` to `on-request` when automatic review was inherited from user config.
The helper checks actual native sandbox, approval policy and reviewer as well
as model/effort, and stops on a mismatch. In the tested installation, even
targeted permission overrides did not establish a strict `never/user` profile;
the worker was stopped and labelled failed, while its read-only sandbox remained
present. Treat unsupported effective permission selection as a blocker, rather
than silently accepting a different mode or disabling managed policy. See the official
[permission defaults](https://learn.chatgpt.com/docs/sandboxing#configure-defaults).
It does not bypass approval, sandbox or configured exec-policy rules. In a
noninteractive run, unavailable approval can fail the action: checkpoint it and
resume in a genuinely authorized runtime, rather than enabling dangerous mode.

Keep `run.json`, `brief.md`, `events.jsonl`, `stderr.log` and `answer.md` outside
published source. Initial `thread.started.thread_id` establishes the durable
session ID. `turn_context` in the exact native transcript records the effective
session model/effort; wait for the new turn when resuming. These records establish
session selection, not hidden backend implementation. A successful exit with no
fresh matching context or no completed turn stays **unverified**, not completed.
This is observation after launch, not a replacement for the client's sandbox.
For an unfamiliar runtime, verify a no-tool, no-sensitive-data probe first.

For durable external processes, launch with stdin detached or prompt delivered
through the helper, logs redirected, and an independent process session/group.
Verify actual owned command/PID/PGID and parent detachment; saved JSON alone is
not durability proof. Keep credentials out of argv and run records. The helper
creates a child process group so a bounded stop targets only its own child tree.

## Exact resume and safe stopping

```bash
python3 scripts/codex_worker.py status /authorized/runs/worker-01
python3 scripts/codex_worker.py run \
  --cwd /authorized/workspace --brief /authorized/correction.md \
  --run-dir /authorized/runs/worker-02 \
  --resume-run /authorized/runs/worker-01 \
  --model gpt-6.1-sol --effort high --timeout 3600
python3 scripts/codex_worker.py stop /authorized/runs/worker-02
```

Resume the latest terminal invocation in the same working directory; the helper
pins the exact UUID with `codex exec resume UUID -`, rejects stale lineage and
holds an exclusive session lock to prevent concurrent resume. It never uses
`--last`. Each invocation keeps its own artifacts. Other runners' records are
not operated by this helper; adopt their documented exact-resume mechanism.
Omitting `--permission` inherits the prior invocation's mode. A change requires
explicit task authorization plus `--allow-permission-change`; model/effort are
always specified. Do not use this flag simply to make a blocked action run.

`stop` writes an owned stop request. The live helper checks it, interrupts only
its child group, preserves evidence, then escalates termination if necessary.
If the helper itself died, its request file cannot stop an orphan: inspect actual
owned process identities before any recovery. Do not kill all Codex processes.
Remote cloud jobs do not disappear when CLI reasoning stops. Inspect their
actual handles/status before retries; stopping a worker does not authorize job
cancellation or duplicate submission.

## Coordination, quotas and parent attention

Separate CLI sessions cannot address another session's collaboration tree by
using its `/root/agent` name. Use owned artifacts/mailboxes or an explicitly
authorized supported messaging route. Preserve disjoint write ownership and
return concrete dependencies. After a review returns actual corrections,
exact-resume the owner. After a dependency arrives, exact-resume the waiting
consumer; do not launch replacement contexts or repeatedly ask for status.

Use current Codex account limits, not Claude's quota API, before substantial
Codex waves. Respect known allowance reserves and never buy credits, enable
overage or change routes on exhaustion. `turn.completed.usage` is invocation
token evidence, not a dollar invoice or account-wide remaining allowance.

Count all owned CLI event logs, native transcripts and children, cache mirrors,
snapshots and temporary evidence under task data limits. Record any newly
installed tooling separately and include it when the task's ceiling covers all
new local material. Model weights and bulk data stay remote when the task requires
that. Permission to delegate does not raise cloud/data caps or credential windows.

Confirm process durability and a same-chat heartbeat when later continuation is
needed. End the parent turn while workers run; perform only useful scheduled
inspections. Completed, dependency-blocked and failed invocations need different
followups. Remove followups after actual completion/cancellation. Parent review
and integration remain required: exit0 or model agreement does not certify work.
