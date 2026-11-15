"""Deliver to the live Desktop/IDE owner, rather than its manual follow-up queue.

The native follower protocol is versioned. Unknown versions or absent owners
stay pending; a lost acknowledgment after submission is never blindly replayed.
"""

import hashlib
import json
import os
import socket
import stat
import struct
import tempfile
import time
import uuid

from ax.config import load


class Unavailable(RuntimeError):
    """Delivery has not started; a later retry is safe."""


class Client:
    def __init__(self, sock):
        self.sock = sock
        self.client_id = "initializing-client"

    def send(self, row):
        raw = json.dumps(row).encode()
        self.sock.sendall(struct.pack("<I", len(raw)) + raw)

    def read(self, size, deadline):
        data = bytearray()
        while len(data) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Codex delivery acknowledgment timed out")
            self.sock.settimeout(remaining)
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise RuntimeError("Codex delivery connection closed before acknowledgment")
            data.extend(chunk)
        return data

    def request(self, method, params, version=0, target=None):
        rid = str(uuid.uuid4())
        row = {
            "type": "request",
            "requestId": rid,
            "sourceClientId": self.client_id,
            "method": method,
            "params": params,
            "version": version,
            "timeoutMs": 10000,
        }
        if target:
            row["targetClientId"] = target
        self.sock.settimeout(12)
        self.send(row)
        deadline = time.monotonic() + 12
        while True:
            size = struct.unpack("<I", self.read(4, deadline))[0]
            if not 0 < size <= 8 * 1024 * 1024:
                raise RuntimeError("Codex delivery returned an invalid frame size")
            try:
                response = json.loads(self.read(size, deadline))
            except ValueError as exc:
                raise RuntimeError("Codex delivery returned invalid JSON") from exc
            if not isinstance(response, dict):
                raise RuntimeError("Codex delivery returned an invalid frame")
            if response.get("type") == "client-discovery-request":
                self.send(
                    {
                        "type": "client-discovery-response",
                        "requestId": response["requestId"],
                        "response": {"canHandle": False},
                    }
                )
            elif response.get("type") == "response" and response.get("requestId") == rid:
                if response.get("resultType") == "success" and response.get("method") != method:
                    raise RuntimeError("Codex delivery acknowledgment method mismatch")
                return response


def endpoints():
    from pathlib import Path

    directory = load().codex_home / "ipc"
    yield directory / "ipc.sock"
    # The native client shortens Unix paths that exceed macOS's socket limit.
    digest = hashlib.sha256(str(directory.resolve()).encode()).hexdigest()
    yield Path("/tmp") / f"codex-ipc-{os.getuid()}" / digest / "ipc.sock"
    yield Path(tempfile.gettempdir()) / "codex-ipc" / f"ipc-{os.getuid()}.sock"


def deliver(sid, text):
    path = None
    for candidate in endpoints():
        try:
            info = candidate.stat()
            if stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid():
                path = candidate
                break
        except OSError:
            continue
    if path is None:
        raise Unavailable("Codex native client is unavailable; delivery remains pending")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        try:
            sock.connect(str(path))
            client = Client(sock)
            reply = client.request("initialize", {"clientType": "ax"})
            client.client_id = reply["result"]["clientId"]
            if (
                reply.get("resultType") != "success"
                or not isinstance(client.client_id, str)
                or not client.client_id
            ):
                raise ValueError("Codex did not initialize delivery")
            owner = client.request(
                "thread-owner-discovery", {"hostId": "local", "conversationId": sid}, version=1
            )
            if owner.get("resultType") != "success" or not isinstance(
                owner.get("handledByClientId"), str
            ):
                raise ValueError("No live Codex client owns the requesting conversation")
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
            raise Unavailable(str(exc)) from exc

        # This is the app's immediate input path. It preserves the conversation's
        # settings and steers an active turn or starts an idle one, without clicks.
        reply = client.request(
            "thread-follower-start-turn",
            {
                "conversationId": sid,
                "turnStart": {
                    "request": {
                        "threadId": sid,
                        "clientUserMessageId": str(uuid.uuid4()),
                        "input": [{"type": "text", "text": text, "text_elements": []}],
                    },
                    "context": {"inheritThreadSettings": True},
                },
            },
            version=2,
            target=owner["handledByClientId"],
        )
        if reply.get("resultType") != "success":
            error = str(reply.get("error", "Codex did not acknowledge delivery"))
            if error in ("no-client-found", "request-version-mismatch", "no-handler-for-request"):
                raise Unavailable(error)
            raise RuntimeError(error)
        result = reply.get("result")
        result = result.get("result") if isinstance(result, dict) else None
        turn = result.get("turn") if isinstance(result, dict) else None
        if (
            not isinstance(turn, dict)
            or not isinstance(turn.get("id"), str)
            or turn.get("status")
            not in (
                "inProgress",
                "completed",
            )
        ):
            raise RuntimeError("Codex did not acknowledge immediate conversation input")
