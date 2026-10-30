"""One search over past conversations and memories.

qmd indexes the archive's conversation notes (one collection per tool, subagents
apart and searched only when asked) and both tools' memories, in a named index of its
own ("ax"), so it never touches another qmd setup. Every hit says where it came from,
and a conversation hit carries its handle, project, tool and date from the archive,
which is also where the project, tool and date filters apply.
"""

import json
import os
import re
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

import yaml

from ax import handles
from ax.store import Store

INDEX = "ax"
SNIPPET = 300
PASSAGE = 180  # characters of a hit's passage, cut around what matched
SOURCES = ("conversations", "memories", "subagents")
DEFAULT = ("conversations", "memories")
STALE = 3600  # seconds: sync refreshes the index at least this often, for edited memories
RETRY_DAEMON = 300  # seconds before starting qmd's daemon again after a try
DAEMON_WAIT = 10.0  # seconds a search waits for a daemon it started to answer
_LABEL = {"claude": "conversation", "codex": "conversation", "subagents": "subagent",
          "claude-memory": "memory", "codex-memory": "memory"}  # fmt: skip
_COLLECTIONS = {
    "conversations": ("claude", "codex"),
    "subagents": ("subagents",),
    "memories": ("claude-memory", "codex-memory"),
}


class FindError(RuntimeError):
    pass


def _run(argv: list, *, timeout: int = 600, env: dict | None = None) -> str:
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, env={**os.environ, **(env or {})}
        )
    except FileNotFoundError:
        raise FindError(f"{argv[0]} is not installed; see `ax index setup`") from None
    except subprocess.TimeoutExpired:
        raise FindError(f"{argv[0]} took over {timeout} s") from None
    if done.returncode != 0:
        raise FindError(
            f"{' '.join(argv[:4])} failed: {(done.stderr or done.stdout).strip()[-400:]}"
        )
    return done.stdout


def qmd_collections(config) -> dict:
    """The qmd collections ax owns, as qmd's index.yml describes them."""
    sessions = str(config.vault / "Sessions")

    def talks(tool):
        return {"path": sessions, "pattern": f"**/????-??-?? {tool} *.md,**/undated {tool} *.md",
                "ignore": ["**/_subagents/**"],
                "context": {"/": f"{tool.title()} conversations archived by ax, one note each"}}  # fmt: skip

    return {
        "claude": talks("claude"),
        "codex": talks("codex"),
        "subagents": {"path": sessions, "pattern": "**/_subagents/*.md", "includeByDefault": False,
                      "context": {"/": "Subagent and worker conversations archived by ax"}},
        "claude-memory": {"path": str(config.claude_home / "projects"), "pattern": "*/memory/*.md",
                          "context": {"/": "Claude Code's saved memories, one folder per project"}},
        "codex-memory": {"path": str(config.codex_home / "memories"), "pattern": "**/*.md",
                         "context": {"/": "Codex's memories and rollout summaries"}},
    }  # fmt: skip


def qmd_config(config) -> Path:
    return config.find_qmd_dir / f"{INDEX}.yml"


def write_qmd_config(config) -> Path:
    path = qmd_config(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"collections": qmd_collections(config)}, sort_keys=False))
    return path


def ready(config) -> bool:
    return qmd_config(config).exists()


def _qmd(config, *args, timeout: int = 600) -> str:
    """Run qmd on ax's own named index, with its config folder made explicit."""
    argv = ["qmd", "--index", INDEX, *args]
    return _run(argv, timeout=timeout, env={"QMD_CONFIG_DIR": str(config.find_qmd_dir)})


def _daemon_up(config) -> bool:
    """Whether `ax index serve` left qmd's HTTP daemon running, with its models loaded."""
    try:
        with urllib.request.urlopen(f"http://localhost:{config.find_qmd_port}/health", timeout=0.5):
            return True
    except OSError:
        return False


def _post(url: str, body: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return json.loads(reply.read())


_tried: dict[str, float] = {}  # when the daemon was last started, by index


def keep_daemon(config, *, start=None, up=None, now: float | None = None) -> bool:
    """Whether qmd's daemon answers, starting it when it doesn't: searches through it skip
    loading models and rewriting the query (12 s, not 45). A start is tried at most every
    few minutes, and never before `ax index setup`."""
    start, up = start or serve, up or _daemon_up
    if up(config):
        return True
    now = time.monotonic() if now is None else now
    key = str(config.find_qmd_dir)
    if (
        not (config.find_qmd_dir / f"{INDEX}.yml").exists()
        or now - _tried.get(key, -1e9) < RETRY_DAEMON
    ):
        return False
    _tried[key] = now
    try:
        start(config)
    except FindError:
        return False
    deadline = time.monotonic() + DAEMON_WAIT
    while not up(config):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.25)
    return True


def serve(config, *, stop: bool = False) -> str:
    """Start or stop qmd's daemon for the ax index: models stay loaded between searches."""
    if stop:
        return _qmd(config, "mcp", "stop").strip()
    return _qmd(config, "mcp", "--http", "--daemon", "--port", str(config.find_qmd_port)).strip()


# qmd's hunk header over a passage, its line number before it or not:
# "81: @@ -80,4 @@ (79 before, 177 after)". And the number qmd puts before each line.
_HUNK = re.compile(r"^\s*(\d+:\s*)?@@ [^@]*@@")
_NUMBER = re.compile(r"^\s*\d+:\s?")


# A Markdown backslash escape: the character it stands for, without the backslash.
_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|<>~])")


def _snippet(text: str) -> str:
    """qmd's passage on one line: without its hunk headers or the line number before each
    line, and its Markdown escapes read as what they stand for."""
    lines = [ln for ln in (text or "").splitlines() if not _HUNK.match(ln)]
    lines = [_ESCAPE.sub(r"\1", _NUMBER.sub("", ln, count=1)) for ln in lines]
    text = re.sub(r"\s+", " ", " ".join(lines)).strip()
    return text if len(text) <= SNIPPET else text[: SNIPPET - 1] + "…"


def _session_rows(config) -> dict:
    if not config.db_path.exists():
        return {}
    with Store(config.db_path) as store:
        rows = store.db.execute(
            "SELECT note_path, session_id, project, provider, started, title FROM sessions "
            "WHERE note_path IS NOT NULL"
        )
        return {r["note_path"]: dict(r) for r in rows}


def _day(value) -> str:
    return str(value or "")[:10]


def _ask_qmd(config, query, collections, *, n, fast) -> list:
    """qmd's hits: a keyword search and, unless `fast`, one by meaning, merged without the
    reranker (five of a search's seven seconds) or the slow query rewriting; from the daemon
    when it runs, else from a qmd process that loads its embedding model."""
    if _daemon_up(config):
        searches = [{"type": "lex", "query": query}]
        searches += [] if fast else [{"type": "vec", "query": query}]
        body = {"searches": searches, "collections": list(collections), "limit": n,
                "rerank": False}  # fmt: skip
        url = f"http://localhost:{config.find_qmd_port}/query"
        try:
            return _post(url, body, timeout=120).get("results") or []
        except (OSError, ValueError):
            pass  # a daemon that just went away: ask qmd directly
    line = " ".join(query.split())  # one line each, as qmd's query document wants
    asked = query if fast else f"lex: {line}\nvec: {line}"
    args = ["search" if fast else "query", asked, "--format", "json", "-n", str(n)]
    args += [] if fast else ["--no-rerank"]
    for name in collections:
        args += ["-c", name]
    return json.loads(_qmd(config, *args) or "[]")


def _from_qmd(config, query, collections, *, n, fast) -> list[dict]:
    found = _ask_qmd(config, query, collections, n=n, fast=fast)
    roots = qmd_collections(config)
    hits = []
    for item in found if isinstance(found, list) else []:
        match = re.match(r"qmd://([^/]+)/([^?]+)", str(item.get("file") or ""))
        if not match or match.group(1) not in roots:
            continue
        collection, rel = match.group(1), unquote(match.group(2))
        hits.append({"source": _LABEL[collection], "collection": collection,
                     "path": str(Path(roots[collection]["path"]) / rel),
                     "title": item.get("title") or Path(rel).stem, "line": item.get("line"),
                     "snippet": _snippet(item.get("snippet") or "")})  # fmt: skip
    return hits


_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
# A conversation note's turns: "## 13:28 · You", then "### Claude" or "### Codex".
_SPEAKER = re.compile(r"^#{2,3}\s+(?:[\d:–-]+\s+·\s+)?(You|Claude|Codex)\s*$")
_TOOL_LINE = re.compile(r"^[-*]\s+(?:ran|read|called|wrote|edited|searched|listed|fetched|"
                        r"started|used|opened|asked|created|deleted|moved|updated)\b")  # fmt: skip
# Words too common to say why a line matched.
_STOP = frozenset(
    "a an and are as at be but by did do does for from how i in is it my of on or "  # noqa: SIM905
    "our so that the this to was we what when where which who why with you".split()
)
# memshare's copy of a memory, made for the other tool.
_MIRROR = re.compile(r"^From (?:Claude Code|Codex)'s memory: ")


def _plain(line: str) -> str:
    """A Markdown line as plain words: links as their text, without emphasis, code ticks,
    list marks, headings, table rules or escapes; a table row's cells joined by dots."""
    text = line.strip()
    if text.startswith("|"):
        cells = [c.strip() for c in text.strip("|").split("|")]
        text = " · ".join(c for c in cells if c and not set(c) <= set("-: "))
    text = re.sub(r"!?\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"!?\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\*\*|__|`", "", text)
    text = re.sub(r"^(?:#{1,6}\s+|[-*+]\s+|>\s*|\d+\.\s+)", "", text)
    return " ".join(_ESCAPE.sub(r"\1", text).split())


def _around(line: str, words: list[str]) -> str:
    """A long line cut to PASSAGE characters around the first word that matched."""
    if len(line) <= PASSAGE:
        return line
    lower = line.lower()
    at = min((lower.find(w) for w in words if w in lower), default=0)
    start = max(0, min(at - PASSAGE // 3, len(line) - PASSAGE))
    cut = line[start : start + PASSAGE].strip()
    return ("…" if start else "") + cut + ("…" if start + PASSAGE < len(line) else "")


def _passage(path: Path, query: str, source: str) -> str | None:
    """What a person knows a hit by, in plain words cut around what matched. For a
    conversation, the line said, by you or the agent, that holds the most of the query's
    words (or, found by meaning alone, what was asked first), never its note's header or
    its tool lines; for a memory, its description; otherwise the line holding the most
    words. None when the file can't be read or nothing in it matches."""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            text = fh.read(2_000_000)
    except OSError:
        return None
    front = _FRONT.match(text)
    body = re.sub(r"<!--.*?-->", "", text[front.end() :] if front else text, flags=re.S)
    if source == "memory" and front:
        about = re.search(r'^description:\s*"?(.*?)"?\s*$', front.group(1), re.M)
        if about and about.group(1):
            return _around(_plain(about.group(1)), [])
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1 and w not in _STOP]
    talk = source in ("conversation", "subagent")
    speaker, first, best, most = None, None, None, 0
    for raw in body.splitlines():
        line = raw.strip()
        turn = _SPEAKER.match(line)
        if turn:
            speaker = turn.group(1)
            continue
        if talk and (speaker is None or _TOOL_LINE.match(line)):
            continue
        plain = _plain(line)
        if len(plain) < 3:
            continue
        said = f"{speaker}: {plain}" if talk else plain
        if first is None and (not talk or speaker == "You"):
            first = said
        score = len({w for w in words if w in plain.lower()})
        if score > most:
            best, most = said, score
    chosen = best or (first if talk else None)
    return _around(chosen, words) if chosen else None


def _memory_project(path: str) -> str | None:
    """The project a Claude memory belongs to, from its folder's name."""
    found = re.search(r"/projects/([^/]+)/memory/", path)
    if not found:
        return None
    folder = found.group(1)
    return folder.split("-Repos-")[-1] if "-Repos-" in folder else folder.strip("-")


def _presented(hits: list[dict], query: str) -> list[dict]:
    """The hits as a person reads them: each passage what it matched, a memory named as
    itself with its project, and memshare's copy of a memory left out beside it."""
    shown, seen = [], set()
    for hit in hits:
        if hit["source"] == "memory":
            hit["title"] = _MIRROR.sub("", hit["title"])
            if hit["title"].lower() in seen:
                continue
            seen.add(hit["title"].lower())
            hit["project"] = hit.get("project") or _memory_project(hit["path"])
        hit["snippet"] = _passage(Path(hit["path"]), query, hit["source"]) or hit["snippet"]
        shown.append(hit)
    return shown


def _keep(hit: dict, *, project, provider, since) -> bool:
    if hit["source"] in ("conversation", "subagent"):
        if project and hit.get("project") != project:
            return False
        if provider and hit.get("provider") != provider:
            return False
        return not (since and _day(hit.get("date")) < since)
    if project and hit["source"] == "memory":
        return project in hit["path"]
    return True


def find(config, query: str, *, sources=DEFAULT, limit: int = 10, project=None, provider=None,
         since=None, fast: bool = False) -> list[dict]:  # fmt: skip
    """Hits from every chosen source, best first, at most `limit`."""
    collections = [c for s in sources for c in _COLLECTIONS.get(s, ())]
    if not collections:
        return []
    filtered = bool(project or provider or since)
    hits = _from_qmd(config, query, collections, n=limit * (4 if filtered else 2), fast=fast)
    rows = _session_rows(config)
    for hit in hits:
        row = rows.get(os.path.relpath(hit["path"], config.vault))
        if row:
            hit.update(handle=handles.tag(row["session_id"]), session=row["session_id"],
                       project=row["project"], provider=row["provider"],
                       date=_day(row["started"]), started=str(row["started"] or ""),
                       title=row["title"] or hit["title"])  # fmt: skip
    kept = [h for h in hits if _keep(h, project=project, provider=provider, since=since)]
    return _presented(kept, query)[:limit]


def text(hits: list[dict]) -> str:
    lines = []
    for i, h in enumerate(hits, 1):
        where = " · ".join(x for x in (h.get("date"), h["title"], h.get("handle"),
                                       h.get("provider"), h.get("project")) if x)  # fmt: skip
        lines += [f"{i}. [{h['source']}] {where}", f"   {h['snippet']}", f"   {h['path']}"]
    return "\n".join(lines) or "no matches"


def _stamp(config) -> Path:
    return config.data / "find-refreshed"


def stale(config) -> bool:
    """Whether the index hasn't been refreshed for STALE seconds (or ever)."""
    try:
        return datetime.now().timestamp() - _stamp(config).stat().st_mtime > STALE
    except OSError:
        return True


def refresh(config, *, complete: bool = False) -> None:
    """Re-register the collections, re-index the conversations and memories that changed,
    and embed what's new.

    qmd stops embedding after 30 minutes and finishes on the next run; `complete`
    lifts that cap, for a first index of the whole archive.
    """
    write_qmd_config(config)
    _qmd(config, "update", timeout=1800)
    if complete:
        _qmd(config, "embed", "--timeout", "0", timeout=6 * 3600)
    else:
        _qmd(config, "embed", timeout=3600)
    _stamp(config).parent.mkdir(parents=True, exist_ok=True)
    _stamp(config).touch()


def setup(config, *, say=print) -> None:
    """Write qmd's collections, then index and embed them."""
    say(f"wrote {write_qmd_config(config)}")
    refresh(config, complete=True)
    say("indexed and embedded the conversations and memories")


def load_cases(path: Path) -> list[dict]:
    cases = yaml.safe_load(Path(path).read_text()) or []
    return [c for c in cases if isinstance(c, dict) and c.get("query") and c.get("expect")]


def evaluate(config, cases: list[dict], *, k: int = 5) -> dict:
    """How many questions find what they expect (a handle or a path fragment) in the top k."""
    misses = []
    for case in cases:
        sources = case.get("in") or DEFAULT
        hits = find(config, case["query"], sources=sources, limit=k)
        expect = str(case["expect"])
        if not any(expect in (h.get("handle") or "") or expect in h["path"] for h in hits):
            misses.append({"query": case["query"], "expect": expect})
    return {"found": len(cases) - len(misses), "total": len(cases), "k": k, "misses": misses,
            "date": datetime.now().isoformat(timespec="minutes")}  # fmt: skip
