# The ax app

What waits for you (rule proposals and review flags, to-dos, failed or flagged
jobs, usage near a limit), Claude and Codex usage on every screen, running jobs,
recent conversations by handle, and a read-only Markdown reader for the vault.

`ax serve` hosts the built app from `src/ax/web/`, so using it needs no Node:

```bash
ax app service --apply                 # serve it from login, restarted if it stops
ax app open                            # start it if needed and open it
ax serve --share cloudflare --notify   # a quick tunnel, with the link sent by ntfy
```

It is a progressive web app: open http://127.0.0.1:8765/ and install it from the
browser (Chrome's install button in the address bar, Safari's File › Add to Dock).
On this Mac it opens without a token; through a tunnel, every request needs the run's
token. Installed, it opens from its last page while the server restarts.

This folder holds its sources. It was generated from
[atelier](https://github.com/EssenceSentry/atelier) (monitor, instrument);
[DEVELOPMENT.md](DEVELOPMENT.md) covers changing it.
