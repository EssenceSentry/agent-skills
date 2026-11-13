"""Append-only binary-safe stdio records shared by workers and attached clients."""

import base64
import json


def records(path, offset=0):
    if not path.exists():
        return [], offset
    result = []
    with path.open("rb") as stream:
        stream.seek(offset)
        for _ in range(128):
            start = stream.tell()
            line = stream.readline()
            if not line or not line.endswith(b"\n"):
                offset = start
                break
            offset = stream.tell()
            result.append(json.loads(line))
    return result, offset


def recent(path):
    if not path.exists():
        return ""
    with path.open("rb") as stream:
        size = stream.seek(0, 2)
        start = max(0, size - 65536)
        stream.seek(start)
        if start:
            stream.readline()
        lines = stream.readlines()
    parts = []
    for line in lines:
        try:
            item = json.loads(line)
            if item.get("type") == "output":
                parts.append(
                    item["stream"]
                    + ": "
                    + base64.b64decode(item["data"]).decode("utf-8", "replace")
                )
        except (ValueError, KeyError):
            continue
    return "".join(parts)[-16000:]
