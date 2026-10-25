"""One search over past conversations, memories, the vault's notes and the code.

qmd indexes the archive's conversation notes (one collection per tool, subagents
apart and searched only when asked), both tools' memories and the vault's own notes,
in a named index of its own ("ax"), so it never touches another qmd setup. Semble
searches the git repositories under the repos root. `find` asks each and interleaves
their rankings by reciprocal rank; every hit says where it came from, and a
conversation hit carries its handle, project, tool and date from the archive, which
is also where the project, tool and date filters apply.
"""

import json
import os
import re
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

import yaml

from ax import handles
from ax.store import Store

INDEX = "ax"
RRF_K = 60
RERANK = 20  # candidates the reranker reads: half qmd's default, half the time
OFF_TOPIC_CODE = 0.3  # weight of code hits for a question that names no code
# A query is about code when it names some: an identifier, a file, a call, or asks where.
_CODE = re.compile(
    r"`[^`]+`|\b\w+_\w+\b|\b[a-z]+[A-Z]\w*\b|\w+\(\)"
    r"|\b\w+\.(?:py|ts|tsx|js|go|rs|sql|ipynb|toml|ya?ml|json|md)\b"
    r"|(?i:\b(?:where is|where are|where do we|which file|function|class|method|module"
    r"|implemented|defined|codebase)\b)"
)
SNIPPET = 300
SOURCES = ("conversations", "memories", "notes", "docs", "code", "subagents")
DEFAULT = ("conversations", "memories", "notes", "docs", "code")
STALE = 3600  # seconds: sync refreshes the index at least this often, for edited docs
_LABEL = {"claude": "conversation", "codex": "conversation", "subagents": "subagent",
          "claude-memory": "memory", "codex-memory": "memory", "notes": "note"}  # fmt: skip
_DOCS = "docs-"  # one collection per repository: docs-<repo>
_COLLECTIONS = {
    "conversations": ("claude", "codex"),
    "subagents": ("subagents",),
    "memories": ("claude-memory", "codex-memory"),
    "notes": ("notes",),
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
        "notes": {"path": str(config.vault), "pattern": "**/*.md",
                  "ignore": ["Sessions/**", "Runs/**", ".obsidian/**"],
                  "context": {"/": "The user's vault: working rules, projects, experiments"}},
        **{f"{_DOCS}{repo.name}": {
            "path": str(repo), "pattern": "docs/**/*.md,*.md",
            "context": {"/": f"Docs of the {repo.name} repository: README, plans, docs folder"}}
           for repo in repos(config)},
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


def repos(config) -> list[Path]:
    """The repositories Semble searches: configured, else every git checkout under the root."""
    if config.find_repos:
        found = list(config.find_repos)
    else:
        root = config.profile_repos_root
        found = sorted(p for p in root.iterdir() if (p / ".git").exists()) if root.is_dir() else []
    return [*found, *(p for p in config.find_extra_repos if p not in found)]


def _qmd(config, *args, timeout: int = 600) -> str:
    """Run qmd on ax's own named index, with its config folder made explicit."""
    argv = ["qmd", "--index", INDEX, *args]
    return _run(argv, timeout=timeout, env={"QMD_CONFIG_DIR": str(config.find_qmd_dir)})


def code_like(query: str) -> bool:
    return bool(_CODE.search(query))


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


def serve(config, *, stop: bool = False) -> str:
    """Start or stop qmd's daemon for the ax index: models stay loaded between searches."""
    if stop:
        return _qmd(config, "mcp", "stop").strip()
    return _qmd(config, "mcp", "--http", "--daemon", "--port", str(config.find_qmd_port)).strip()


def _snippet(text: str) -> str:
    lines = [ln for ln in (text or "").splitlines() if not ln.startswith("@@")]
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
    """qmd's hits: from the daemon when it runs (a keyword and a vector search, reranked,
    without the slow query rewriting), else from a qmd process that loads its models."""
    if _daemon_up(config):
        searches = [{"type": "lex", "query": query}]
        searches += [] if fast else [{"type": "vec", "query": query}]
        body = {"searches": searches, "collections": list(collections), "limit": n,
                "rerank": not fast, "candidateLimit": RERANK}  # fmt: skip
        url = f"http://localhost:{config.find_qmd_port}/query"
        try:
            return _post(url, body, timeout=120).get("results") or []
        except (OSError, ValueError):
            pass  # a daemon that just went away: ask qmd directly
    args = ["search" if fast else "query", query, "--format", "json", "-n", str(n)]
    args += [] if fast else ["-C", str(RERANK)]
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
        doc = collection.startswith(_DOCS)
        hits.append({"source": "doc" if doc else _LABEL[collection], "collection": collection,
                     **({"project": collection.removeprefix(_DOCS)} if doc else {}),
                     "path": str(Path(roots[collection]["path"]) / rel),
                     "title": item.get("title") or Path(rel).stem, "line": item.get("line"),
                     "snippet": _snippet(item.get("snippet") or "")})  # fmt: skip
    return hits


def _from_semble(config, query, paths, *, n) -> list[dict]:
    argv = ["semble", "search", query, *map(str, paths), "-k", str(n), "--format", "json",
            "--max-snippet-lines", "12"]  # fmt: skip
    found = json.loads(_run(argv) or "{}")
    roots = found.get("repos") or {}
    if not roots and len(paths) == 1:
        roots = {"": str(paths[0])}
    hits = []
    for item in found.get("results") or []:
        rel = str(item.get("file_path") or "")
        repo, _, inner = rel.partition("/") if len(roots) > 1 or "" not in roots else ("", "", rel)
        base = roots.get(repo)
        if base is None:
            continue
        path = Path(base) / inner
        name = Path(base).name
        span = f"{item.get('start_line')}-{item.get('end_line')}"
        hits.append({"source": "code", "path": str(path), "project": name,
                     "title": f"{name}/{inner}:{span}", "line": item.get("start_line"),
                     "snippet": _snippet(item.get("content") or "")})  # fmt: skip
    return hits


def _keep(hit: dict, *, project, provider, since) -> bool:
    if hit["source"] in ("conversation", "subagent"):
        if project and hit.get("project") != project:
            return False
        if provider and hit.get("provider") != provider:
            return False
        return not (since and _day(hit.get("date")) < since)
    if project and hit["source"] in ("memory", "note"):
        return project in hit["path"]
    return True


def find(config, query: str, *, sources=DEFAULT, limit: int = 10, project=None, provider=None,
         since=None, fast: bool = False) -> list[dict]:  # fmt: skip
    """Hits from every chosen source, best first, at most `limit`."""
    sources = [s for s in sources if s in SOURCES]
    filtered = bool(project or provider or since)
    n = limit * (4 if filtered else 2)
    paths = [p for p in repos(config) if not project or p.name == project]
    collections = [c for s in sources for c in _COLLECTIONS.get(s, ())]
    collections += [f"{_DOCS}{p.name}" for p in paths] if "docs" in sources else []
    with ThreadPoolExecutor(max_workers=2) as pool:  # qmd and Semble at once
        asked = (
            pool.submit(_from_qmd, config, query, collections, n=n, fast=fast)
            if collections
            else None
        )
        coded = (
            pool.submit(_from_semble, config, query, paths, n=n)
            if "code" in sources and paths
            else None
        )
        notes, code = (asked.result() if asked else None), (coded.result() if coded else None)
    lists = []  # (weight, hits)
    if notes is not None:
        hits = notes
        rows = _session_rows(config)
        for hit in hits:
            row = rows.get(os.path.relpath(hit["path"], config.vault))
            if row:
                hit.update(handle=handles.tag(row["session_id"]), project=row["project"],
                           provider=row["provider"], date=_day(row["started"]),
                           title=row["title"] or hit["title"])  # fmt: skip
        kept = [h for h in hits if _keep(h, project=project, provider=provider, since=since)]
        lists.append((1.0, kept))
    if code is not None:
        about_code = code_like(query) or list(sources) == ["code"]
        lists.append((1.0 if about_code else OFF_TOPIC_CODE, code))
    scored = [
        (weight / (RRF_K + rank), order, hit)
        for order, (weight, hits) in enumerate(lists)
        for rank, hit in enumerate(hits, 1)
    ]
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [hit for _, _, hit in scored[:limit]]


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
    """Re-register the collections (repos cloned since get theirs), re-index changed notes,
    memories and docs, and embed what's new; Semble re-indexes code on its own.

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
    """Write qmd's collections, index and embed them, and index every repository."""
    say(f"wrote {write_qmd_config(config)}")
    refresh(config, complete=True)
    say("indexed and embedded the conversations, memories and notes")
    for path in repos(config):
        _run(["semble", "search", "setup", str(path), "-k", "1"], timeout=1800)
        say(f"indexed {path}")


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
