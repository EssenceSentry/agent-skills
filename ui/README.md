# The ax app

What waits for you (rule proposals and review flags, to-dos, failed or flagged
jobs, usage near a limit), Claude and Codex usage on every screen, running jobs,
recent conversations by handle, and a read-only Markdown reader for the vault.

`ax serve` hosts the built app from `src/ax/web/`, so using it needs no Node:

```bash
ax serve --open                        # this Mac
ax serve --share cloudflare --notify   # a quick tunnel, with the link sent by ntfy
```

This folder holds its sources. It was generated from
[atelier](https://github.com/EssenceSentry/atelier) (monitor, instrument);
[DEVELOPMENT.md](DEVELOPMENT.md) covers changing it.
