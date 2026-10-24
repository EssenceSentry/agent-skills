"""The normalized session that every source parser produces."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Event:
    """One step of a conversation: a message, a tool call or a notice."""

    kind: str  # "user", "assistant", "tool" or "notice"
    text: str
    ts: datetime | None = None
    tool: str | None = None
    ok: bool | None = None
    output: str = ""
    child: str | None = None  # session id of a subagent this tool call started


@dataclass
class Session:
    provider: str  # "claude" or "codex"
    session_id: str
    kind: str = "main"  # "main", "subagent" or "guardian"
    parent_id: str | None = None
    title: str | None = None
    cwd: str | None = None
    project: str = "unknown"
    branch: str | None = None
    model: str | None = None
    effort: str | None = None
    entrypoint: str | None = None
    version: str | None = None
    started: datetime | None = None
    ended: datetime | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None
    events: list[Event] = field(default_factory=list)
    unknown: Counter = field(default_factory=Counter)
    source_path: Path | None = None

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.session_id}"

    @property
    def parent_key(self) -> str | None:
        return f"{self.provider}:{self.parent_id}" if self.parent_id else None

    @property
    def user_turns(self) -> int:
        return sum(e.kind == "user" for e in self.events)

    @property
    def tool_calls(self) -> int:
        return sum(e.kind == "tool" for e in self.events)
