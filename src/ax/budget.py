"""Budgets agents register, add to and ask about: "no more than $40 on annotations".

A budget has a limit in any unit. Agents add what they spend, or reserve an amount
before an expensive call and settle it with the real figure afterwards; a hold that is
never settled keeps counting, so a crash never makes spending vanish and parallel workers
can't overshoot together. A budget with a folder measures that folder's size instead of
taking additions. Going over is refused unless a reason is given, which is logged on the
budget.

The ledger is SQLite in ax's data folder, so concurrent agents write safely, and this
module stays on the standard library so ax-guard and the app can read it cheaply.
"""

import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

NEAR = 0.8  # share of the limit at which a budget is near it
SIZES = {"b": 1, "kb": 10**3, "mb": 10**6, "gb": 10**9, "tb": 10**12}
_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_SLACK = 1e-9  # float sums: an amount that exactly reaches the limit fits

_SCHEMA = """
create table if not exists budgets (
  id integer primary key, name text not null, cap real not null, unit text not null,
  why text, owner text, scope text, project text, path text, created text not null,
  closed text
);
create table if not exists entries (
  id integer primary key, budget integer not null references budgets(id),
  kind text not null, amount real not null, note text, agent text, intent text,
  at text not null, state text, actual real, settled text
);
create index if not exists entries_budget on entries(budget);
"""


class BudgetError(ValueError):
    pass


class OverLimit(BudgetError):
    pass


def ledger_path(data) -> Path:
    return Path(data) / "budgets.sqlite"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _connect(data) -> sqlite3.Connection:
    path = ledger_path(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("pragma busy_timeout = 30000")
    db.executescript(_SCHEMA)
    return db


def number(x: float) -> str:
    """43.0 -> "43", 12.25 -> "12.25", 0.0015 -> "0.0015"."""
    return f"{round(x, 6):,.6f}".rstrip("0").rstrip(".")


def _positive(amount, what: str) -> float:
    try:
        value = float(amount)
    except (TypeError, ValueError):
        raise BudgetError(f"{what} must be a positive number, not {amount!r}") from None
    if not value > 0:
        raise BudgetError(f"{what} must be a positive number, not {number(value)}")
    return value


def folder_size(path: str) -> int:
    """Bytes in the files under `path`, without following links; 0 when it's missing."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                continue
    return total


def _open(db, name: str) -> sqlite3.Row:
    row = db.execute("select * from budgets where name = ? and closed is null", (name,)).fetchone()
    if row is None:
        raise BudgetError(f"no open budget {name}; see `ax budget show`")
    return row


def _measure(row) -> float:
    return folder_size(row["path"]) / SIZES[row["unit"].lower()]


def _totals(db, row) -> tuple[float, float]:
    spent, reserved = db.execute(
        "select coalesce(sum(case when kind = 'add' then amount end), 0),"
        " coalesce(sum(case when kind = 'hold' and state = 'open' then amount end), 0)"
        " from entries where budget = ?",
        (row["id"],),
    ).fetchone()
    if row["path"]:
        spent = _measure(row)
    return round(spent, 9), round(reserved, 9)


def _state(cap: float, committed: float) -> str:
    if committed > cap + _SLACK:
        return "over"
    return "near" if committed >= NEAR * cap - _SLACK else "ok"


def _status(db, row) -> dict:
    spent, reserved = _totals(db, row)
    passes = db.execute(
        "select count(*) from entries where budget = ? and intent is not null", (row["id"],)
    ).fetchone()[0]
    return {
        "name": row["name"], "cap": row["cap"], "unit": row["unit"], "why": row["why"],
        "owner": row["owner"], "scope": row["scope"], "project": row["project"],
        "path": row["path"],
        "created": row["created"], "spent": spent, "reserved": reserved,
        "left": round(row["cap"] - spent - reserved, 9),
        "state": _state(row["cap"], spent + reserved), "passes": passes,
    }  # fmt: skip


def _over(db, row, amount: float, intent: str | None) -> None:
    """Refuse an amount that would take the budget past its limit, unless a reason is given."""
    spent, reserved = _totals(db, row)
    after = spent + reserved + amount
    if after <= row["cap"] + _SLACK or intent:
        return
    held = f", {number(reserved)} of it reserved" if reserved else ""
    raise OverLimit(
        f"{row['name']} would reach {number(after)} of {number(row['cap'])} {row['unit']}, "
        f"{number(after - row['cap'])} over (now {number(spent + reserved)}{held})"
    )


def create(data, name: str, cap, unit: str, *, why=None, owner=None, scope=None,
           project=None, path=None) -> dict:  # fmt: skip
    """Open a budget, or change the limit of the open one with this name. `owner` is the
    handle of the conversation that set it; `scope` is "session:<id>" for that
    conversation and its subagents, or "project:<name>"."""
    if not _NAME.fullmatch(name or ""):
        raise BudgetError(
            f"{name!r} can't be a budget name: use lower-case letters, digits, '.', '_' or '-'"
        )
    cap = _positive(cap, "a limit")
    unit = (unit or "").strip()
    if not unit:
        raise BudgetError("a budget needs its unit, such as usd, GB, hours or calls")
    if path is not None:
        if unit.lower() not in SIZES:
            raise BudgetError(
                f"a budget that measures a folder needs a size unit ({', '.join(SIZES)}), "
                f"not {unit}"
            )
        path = str(Path(path).expanduser().resolve())
    with closing(_connect(data)) as db:
        db.execute("begin immediate")
        row = db.execute(
            "select * from budgets where name = ? and closed is null", (name,)
        ).fetchone()
        if row is None:
            db.execute(
                "insert into budgets (name, cap, unit, why, owner, scope, project, path,"
                " created) values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (name, cap, unit, why, owner, scope, project, path, _now()),
            )
        elif row["unit"] != unit or (path is not None and row["path"] != path):
            db.execute("rollback")
            raise BudgetError(
                f"{name} counts {row['unit']}"
                f"{' in ' + row['path'] if row['path'] else ''}; close it first to change that"
            )
        else:
            db.execute(
                "update budgets set cap = ?, why = coalesce(?, why) where id = ?",
                (cap, why, row["id"]),
            )
        db.execute("commit")
        return _status(db, _open(db, name))


def add(data, name: str, amount, *, note=None, agent=None, intent=None) -> dict:
    """Record what was spent; refused if it goes over the limit without a reason."""
    amount = _positive(amount, "an amount")
    with closing(_connect(data)) as db:
        db.execute("begin immediate")
        try:
            row = _open(db, name)
            if row["path"]:
                raise BudgetError(
                    f"{name} measures its folder {row['path']}; reserve before a download "
                    "instead of adding to it"
                )
            _over(db, row, amount, intent)
            db.execute(
                "insert into entries (budget, kind, amount, note, agent, intent, at)"
                " values (?, 'add', ?, ?, ?, ?, ?)",
                (row["id"], amount, note, agent, intent, _now()),
            )
        except BaseException:
            db.execute("rollback")
            raise
        db.execute("commit")
        return _status(db, row)


def fits(data, name: str, amount) -> bool:
    amount = _positive(amount, "an amount")
    with closing(_connect(data)) as db:
        row = _open(db, name)
        spent, reserved = _totals(db, row)
        return spent + reserved + amount <= row["cap"] + _SLACK


def check(data, name: str, amount, *, agent=None, intent=None) -> dict:
    """Whether the next amount fits; refused when it doesn't, unless a reason is given,
    which is logged on the budget without counting anything."""
    amount = _positive(amount, "an amount")
    with closing(_connect(data)) as db:
        row = _open(db, name)
        _over(db, row, amount, intent)
        spent, reserved = _totals(db, row)
        if intent and spent + reserved + amount > row["cap"] + _SLACK:
            db.execute(
                "insert into entries (budget, kind, amount, agent, intent, at)"
                " values (?, 'pass', ?, ?, ?, ?)",
                (row["id"], amount, agent, intent, _now()),
            )
        return _status(db, row)


def reserve(data, name: str, amount, *, note=None, agent=None, intent=None) -> str:
    """Hold an amount before spending it; returns the ticket to settle or release."""
    amount = _positive(amount, "an amount")
    with closing(_connect(data)) as db:
        db.execute("begin immediate")
        try:
            row = _open(db, name)
            _over(db, row, amount, intent)
            cursor = db.execute(
                "insert into entries (budget, kind, amount, note, agent, intent, at, state)"
                " values (?, 'hold', ?, ?, ?, ?, ?, 'open')",
                (row["id"], amount, note, agent, intent, _now()),
            )
        except BaseException:
            db.execute("rollback")
            raise
        db.execute("commit")
        return f"R{cursor.lastrowid}"


def _hold(db, ticket: str) -> sqlite3.Row:
    found = re.fullmatch(r"R(\d+)", (ticket or "").strip())
    row = (
        found
        and db.execute(
            "select e.*, b.name, b.path, b.closed from entries e join budgets b on b.id = e.budget"
            " where e.id = ? and e.kind = 'hold'",
            (int(found.group(1)),),
        ).fetchone()
    )
    if not row:
        raise BudgetError(f"no reservation {ticket}")
    if row["state"] != "open":
        raise BudgetError(f"reservation {ticket} is already {row['state']}")
    return row


def settle(data, ticket: str, actual=None, *, agent=None) -> dict:
    """Replace a hold with what was really spent. A folder budget measures the download
    itself, so there the hold is only closed."""
    with closing(_connect(data)) as db:
        db.execute("begin immediate")
        try:
            hold = _hold(db, ticket)
            if not hold["path"]:
                if actual is None:
                    raise BudgetError(f"settling {ticket} needs what was really spent")
                actual = float(actual)
                if actual < 0:
                    raise BudgetError("what was spent can't be negative")
            when = _now()
            db.execute(
                "update entries set state = 'settled', actual = ?, settled = ? where id = ?",
                (actual, when, hold["id"]),
            )
            if not hold["path"] and actual > 0:
                db.execute(
                    "insert into entries (budget, kind, amount, note, agent, intent, at)"
                    " values (?, 'add', ?, ?, ?, ?, ?)",
                    (hold["budget"], actual, hold["note"] or f"settles {ticket}",
                     agent or hold["agent"], hold["intent"], when),
                )  # fmt: skip
        except BaseException:
            db.execute("rollback")
            raise
        db.execute("commit")
        return _status(db, db.execute("select * from budgets where id = ?",
                                      (hold["budget"],)).fetchone())  # fmt: skip


def release(data, ticket: str) -> dict:
    """Return a hold that wasn't spent."""
    with closing(_connect(data)) as db:
        db.execute("begin immediate")
        try:
            hold = _hold(db, ticket)
            db.execute(
                "update entries set state = 'released', settled = ? where id = ?",
                (_now(), hold["id"]),
            )
        except BaseException:
            db.execute("rollback")
            raise
        db.execute("commit")
        return _status(db, db.execute("select * from budgets where id = ?",
                                      (hold["budget"],)).fetchone())  # fmt: skip


def close(data, name: str) -> dict:
    with closing(_connect(data)) as db:
        row = _open(db, name)
        found = _status(db, row)
        db.execute("update budgets set closed = ? where id = ?", (_now(), row["id"]))
        return found | {"closed": True}


def status(data, name: str) -> dict:
    with closing(_connect(data)) as db:
        return _status(db, _open(db, name))


def statuses(data, *, scopes=None, project=None) -> list[dict]:
    """Every open budget, oldest first; with `scopes`, those set for one of them; with
    `project`, those of that project."""
    if not ledger_path(data).exists():
        return []
    with closing(_connect(data)) as db:
        rows = db.execute("select * from budgets where closed is null order by id").fetchall()
        found = [_status(db, row) for row in rows]
    if scopes is not None:
        found = [x for x in found if x["scope"] is None or x["scope"] in scopes]
    if project is not None:
        found = [x for x in found if x["project"] in (None, project)]
    return found


def entries(data, name: str, *, limit: int = 50) -> list[dict]:
    """The ledger of an open budget, newest first."""
    with closing(_connect(data)) as db:
        row = _open(db, name)
        rows = db.execute(
            "select * from entries where budget = ? order by id desc limit ?", (row["id"], limit)
        ).fetchall()
    return [
        {"ticket": f"R{r['id']}" if r["kind"] == "hold" else None, "kind": r["kind"],
         "amount": r["amount"], "note": r["note"], "agent": r["agent"], "intent": r["intent"],
         "at": r["at"], "state": r["state"], "actual": r["actual"]}
        for r in rows
    ]  # fmt: skip
