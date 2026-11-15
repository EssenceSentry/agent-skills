import json
import socket
import struct
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ax import codex_delivery, providers


def read(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise EOFError
        data.extend(chunk)
    return data


def receive(sock):
    return json.loads(read(sock, struct.unpack("<I", read(sock, 4))[0]))


def send(sock, row):
    raw = json.dumps(row).encode()
    frame = struct.pack("<I", len(raw)) + raw
    # A stream can split both its header and payload across reads.
    for part in (frame[:2], frame[2:7], frame[7:]):
        sock.sendall(part)


@pytest.fixture
def peer(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="ax-delivery-", dir="/tmp") as directory:
        path = Path(directory) / "ipc.sock"
        monkeypatch.setattr(codex_delivery, "endpoints", lambda: iter([path]))
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path))
            server.listen()
            server.settimeout(3)
            with ThreadPoolExecutor(max_workers=1) as pool:

                def launch(mode="live"):
                    seen = []

                    def serve():
                        with server.accept()[0] as sock:
                            sock.settimeout(3)
                            while True:
                                try:
                                    row = receive(sock)
                                except EOFError:
                                    return
                                seen.append(row)
                                reply = dict(
                                    type="response",
                                    requestId=row["requestId"],
                                    method=row["method"],
                                    resultType="success",
                                )
                                if row["method"] == "initialize":
                                    reply["result"] = {"clientId": "ax-client"}
                                elif row["method"] == "thread-owner-discovery":
                                    if mode == "absent":
                                        reply.update(resultType="error", error="no-client-found")
                                    else:
                                        send(
                                            sock,
                                            dict(
                                                type="client-discovery-request",
                                                requestId="discover-ax",
                                                request={},
                                            ),
                                        )
                                        discovery = receive(sock)
                                        assert discovery["response"]["canHandle"] is False
                                        reply.update(handledByClientId="live-owner", result={})
                                else:
                                    assert row["method"] == "thread-follower-start-turn"
                                    if mode == "lost-ack":
                                        return
                                    if mode == "invalid-json":
                                        sock.sendall(struct.pack("<I", 1) + b"{")
                                        return
                                    if mode == "oversized":
                                        sock.sendall(struct.pack("<I", 9 * 1024 * 1024))
                                        return
                                    if mode == "version-mismatch":
                                        reply.update(
                                            resultType="error", error="request-version-mismatch"
                                        )
                                    elif mode == "queued-only":
                                        reply["result"] = {"messageId": "queued"}
                                    elif mode == "error":
                                        reply.update(
                                            resultType="error", error="turn dispatch failed"
                                        )
                                    elif mode == "malformed-turn":
                                        reply["result"] = {"result": {"turn": []}}
                                    else:
                                        reply["result"] = {
                                            "result": {
                                                "turn": {"id": "live-turn", "status": "inProgress"}
                                            }
                                        }
                                    send(sock, reply)
                                    return
                                send(sock, dict(type="broadcast", method="unrelated"))
                                send(sock, reply)

                    return seen, pool.submit(serve)

                yield launch


def test_codex_delivery_reaches_live_owner_without_queue_or_setting_overrides(peer):
    seen, finished = peer()
    providers.deliver({"owner": "codex:original-session"}, "evidence-bearing concern")
    finished.result(timeout=3)
    submit = seen[-1]
    assert submit["targetClientId"] == "live-owner" and submit["version"] == 2
    start = submit["params"]["turnStart"]
    assert start["request"]["threadId"] == "original-session"
    assert start["request"]["input"][0]["text"] == "evidence-bearing concern"
    assert set(start["request"]) == {"threadId", "clientUserMessageId", "input"}
    assert start["context"] == {"inheritThreadSettings": True}


def test_absent_owner_is_retryable_without_submitting_chat_input(peer):
    seen, finished = peer("absent")
    with pytest.raises(providers.Unavailable):
        providers.deliver({"owner": "codex:original-session"}, "concern")
    finished.result(timeout=3)
    assert [row["method"] for row in seen] == ["initialize", "thread-owner-discovery"]


@pytest.mark.parametrize(
    "mode", ["lost-ack", "queued-only", "error", "invalid-json", "oversized", "malformed-turn"]
)
def test_unconfirmed_dispatch_is_never_reported_as_accepted(peer, mode):
    seen, finished = peer(mode)
    with pytest.raises(RuntimeError) as failure:
        providers.deliver({"owner": "codex:original-session"}, "concern")
    assert not isinstance(failure.value, providers.Unavailable)
    finished.result(timeout=3)
    assert len([row for row in seen if row["method"] == "thread-follower-start-turn"]) == 1


def test_version_rejection_before_submission_is_retryable(peer):
    seen, finished = peer("version-mismatch")
    with pytest.raises(providers.Unavailable, match="version-mismatch"):
        providers.deliver({"owner": "codex:original-session"}, "concern")
    finished.result(timeout=3)


def test_no_native_socket_does_not_fall_back_to_manual_queue(monkeypatch, tmp_path):
    monkeypatch.setattr(codex_delivery, "endpoints", lambda: iter([tmp_path / "missing.sock"]))
    with pytest.raises(providers.Unavailable, match="remains pending"):
        providers.deliver({"owner": "codex:original-session"}, "concern")
