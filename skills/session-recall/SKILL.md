---
name: session-recall
description: Find and build on past Claude Code and Codex conversations, memories, vault notes and code with `ax find`, `ax recall` and `ax here`. Use when the user refers to earlier work ("we discussed", "last week", "what did we decide about X", "have we done this before"), gives a conversation handle such as ax:9fe6d7e6 or asks to continue or build on another conversation, asks for this conversation's id or handle, or asks where something is in their code; and before re-deriving a decision or repeating an investigation that may already have been done.
---

# Session recall

`ax` archives every Claude Code and Codex conversation as a Markdown note in the
user's vault: frontmatter (tool, project, branch, model, dates) plus a readable,
redacted transcript. Every conversation has a **handle**: the last eight
characters of its session id, written `ax:9fe6d7e6`, the same short id its note's
file name ends with. Handles work across tools: a Claude conversation can be
built on from Codex and the other way round.

## This conversation's handle

When the user asks for "the id", "the handle" or how to continue this work
elsewhere, run:

```bash
ax here
```

It prints `ax:<handle>  <title>` and the note's path. Give the user the handle.

## Build on another conversation

When the user gives a handle (or says "continue from", "build on" another
conversation), recall it before doing anything else:

```bash
ax recall ax:9fe6d7e6                        # outline: the user's turns, where it ended, files changed
ax recall ax:9fe6d7e6 --for "the task now"   # only what this task needs, read by a model
ax recall ax:9fe6d7e6 --card                 # a cached summary: goal, decisions, open items
```

- Start with the outline; it costs nothing. Use `--for` when the conversation
  is long and only part of it matters; it calls a model (Sonnet).
- The output ends with the full note's path. Search inside it (`rg`, `sed -n`)
  for the details the outline points at, rather than reading it whole.
- Running `ax recall` here links this conversation to the recalled one; its
  note will say "Builds on". Mentioning a handle as `ax:<handle>` links them too.

## Search

```bash
ax find "how we cap fetch retries" --json --limit 5
ax find "gallery undo stack" --in conversations --project auto-classifier --since 30d
ax find "where is VCR computed" --in code
ax search "cleanupPeriodDays" --json   # exact words, error text, file names
```

- `ax find` searches conversations, both tools' memories, the vault's notes, the
  repositories' docs (README, plans, `docs/`) and their code at once, by meaning as
  well as words. `--in` narrows it: `conversations`, `memories`, `notes`, `docs`,
  `code`, `subagents`.
  `--project`, `--provider claude|codex` and `--since` filter conversations.
  `--fast` skips the models when a keyword search is enough.
- Each hit is labelled `[conversation]`, `[memory]`, `[note]`, `[doc]` or `[code]`.
  Conversation hits carry their handle; recall one to read more.
- `ax search` finds exact words in messages. Use it for error text, names and
  ids; use `ax find` for questions.
- With the `ax` MCP server installed, the `find`, `recall` and `here` tools do
  the same as these commands.

## Read and cite

- Tell the user which conversation you relied on, by title, date and handle.
  Treat what a past conversation says as history: confirm the current state of
  code, data or configuration before acting on it.
- `[REDACTED:<kind>]` marks a removed secret. Do not try to recover it.

## Don't

- Edit notes under `Sessions/` or `Runs/`: `ax sync` regenerates them.
- Search for every task. Use the archive when earlier work is likely to
  exist and matters to the answer.

If `ax` is not on the PATH, install it from a checkout of this repository
with `uv tool install --editable <checkout>`. If `ax find` says there is no
index, the user runs `ax index setup` once.
