---
name: session-recall
description: Search the archive of past Claude Code and Codex sessions with `ax search`. Use when the user refers to earlier work ("we discussed", "last week", "what did we decide about X"), before re-deriving a decision or repeating an investigation that may already have been done, and when a task continues work from another session. Returns the matching session notes in the Obsidian vault.
---

# Session recall

Every Claude Code and Codex session is archived by `ax` as a Markdown note:
frontmatter (provider, project, branch, model, dates) plus a readable
transcript. `ax search` finds them by what was said.

## Search

```bash
ax search "vault private repo" --json --limit 5
ax search "cleanupPeriodDays" --project my-repo --since 14d --json
```

- Every word must appear in one message, so use two to four distinctive
  words: names, error text, file names. With no match, try synonyms or fewer
  words. Exit code 1 means no matches.
- Filters: `--provider claude|codex`, `--project <git repo name>`,
  `--role user|assistant|tool|notice|message`, `--since YYYY-MM-DD|7d|2w`.
  Searching with `--role user` finds what the user asked for or decided.
- Each JSON hit has `title`, `started`, `project`, `snippet` and `note`, the
  note's full path.

## Read and cite

- Open the `note` path for context. Notes can be long, so search inside the
  note for the snippet's words and read around them rather than reading it
  whole.
- Tell the user which session you relied on, by title and date. Treat what a
  past session says as history: confirm the current state of code, data or
  configuration before acting on it.
- `[REDACTED:<kind>]` marks a removed secret. Do not try to recover it.

## Don't

- Edit notes under `Sessions/` or `Runs/`: `ax sync` regenerates them.
- Search for every task. Use the archive when earlier work is likely to
  exist and matters to the answer.

If `ax` is not on the PATH, install it from a checkout of this repository
with `uv tool install --editable <checkout>`.
