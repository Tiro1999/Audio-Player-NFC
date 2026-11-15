"""Tests for nfc_player.spotify.receiver; FakeUrlopen stands in for go-librespot's API."""

import http.client
import io
import json
import urllib.error
from dataclasses import dataclass
from typing import Any

import pytest

from nfc_player.spotify.receiver import Receiver, ReceiverError, ReceiverNotReady, ReceiverStatus

BASE = "http://127.0.0.1:3678"
REFUSED = urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
PLAYING = {"stopped": False, "paused": False, "buffering": False, "context_uri": "spotify:album:abc"}


@dataclass
class SentRequest:
    method: str
    url: str
    body: Any
    content_type: str | None
    timeout: float | None


class FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeUrlopen:
    """Records each request and answers with the next scripted reply, like urllib's opener.

    A reply is an exception to raise or (status, body); a status >= 400 raises HTTPError.
    """

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.requests: list[SentRequest] = []

    def __call__(self, request, timeout=None):
        sent = json.loads(request.data) if request.data is not None else None
        self.requests.append(
            SentRequest(
                request.get_method(), request.full_url, sent, request.get_header("Content-type"), timeout
            )
        )
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        status, body = reply
        if isinstance(body, dict | list):
            body = json.dumps(body).encode()
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "error", None, io.BytesIO(body))
        return FakeResponse(status, body)


def make(*replies: Any, **kwargs: Any) -> tuple[Receiver, FakeUrlopen]:
    fake = FakeUrlopen(*replies)
    return Receiver(BASE, urlopen=fake, **kwargs), fake


def test_play_posts_json_uri():
    receiver, fake = make((200, b"null"), timeout=2.5)
    receiver.play("spotify:album:abc")
    # Exactly one request: play never touches the shuffle state.
    assert fake.requests == [
        SentRequest("POST", f"{BASE}/player/play", {"uri": "spotify:album:abc"}, "application/json", 2.5)
    ]


def test_default_timeout_is_five_seconds():
    receiver, fake = make((200, b""))
    receiver.play("spotify:track:abc")
    assert fake.requests[0].timeout == 5.0


def test_pause_and_resume_paths():
    receiver, fake = make((200, b""), (200, b""))
    receiver.pause()
    receiver.resume()
    assert [(r.method, r.url, r.body) for r in fake.requests] == [
        ("POST", f"{BASE}/player/pause", None),
        ("POST", f"{BASE}/player/resume", None),
    ]


def test_base_url_trailing_slash_is_ignored():
    fake = FakeUrlopen((200, b""))
    Receiver(BASE + "/", urlopen=fake).pause()
    assert fake.requests[0].url == f"{BASE}/player/pause"


def test_status_parses_paused():
    receiver, fake = make((200, {**PLAYING, "paused": True, "track": {"uri": "spotify:track:x"}}))
    assert receiver.status() == ReceiverStatus(stopped=False, paused=True)
    assert (fake.requests[0].method, fake.requests[0].url) == ("GET", f"{BASE}/status")


def test_status_playing():
    receiver, _ = make((200, PLAYING))
    assert receiver.status() == ReceiverStatus(stopped=False, paused=False)


def test_status_idle_means_stopped():
    idle = {"stopped": True, "paused": False, "buffering": False, "context_uri": None, "track": None}
    receiver, _ = make((200, idle))
    assert receiver.status() == ReceiverStatus(stopped=True, paused=False)


def test_status_204_means_stopped():
    receiver, _ = make((204, b""))
    assert receiver.status() == ReceiverStatus(stopped=True, paused=False)


@pytest.mark.parametrize(
    "body",
    [b"not json", b"\xff\xfe\xfa", b"[]", b"null", {"stopped": "false", "paused": False}, {"paused": False}],
)
def test_status_rejects_unexpected_body(body):
    receiver, _ = make((200, body))
    with pytest.raises(ReceiverError):
        receiver.status()


def test_play_204_raises_not_ready():
    receiver, _ = make((204, b""), device_name="Kinderzimmer")
    with pytest.raises(ReceiverNotReady) as raised:
        receiver.play("spotify:track:abc")
    assert isinstance(raised.value, ReceiverError)
    assert "'Kinderzimmer'" in str(raised.value)
    assert "Spotify app" in str(raised.value)


def test_not_ready_hint_uses_default_name():
    receiver, _ = make((204, b""))
    with pytest.raises(ReceiverNotReady, match="'NFC-Box'"):
        receiver.play("spotify:track:abc")


@pytest.mark.parametrize("command", ["pause", "resume"])
def test_pause_and_resume_204_raise_not_ready(command):
    receiver, _ = make((204, b""))
    with pytest.raises(ReceiverNotReady):
        getattr(receiver, command)()


def test_play_raises_receiver_error_on_connection_refused():
    receiver, _ = make(REFUSED)
    with pytest.raises(ReceiverError, match="Connection refused") as raised:
        receiver.play("spotify:track:abc")
    assert not isinstance(raised.value, ReceiverNotReady)


def test_play_raises_receiver_error_on_http_500():
    receiver, _ = make((500, {"error": "failed resolving context"}))
    with pytest.raises(ReceiverError, match="HTTP 500") as raised:
        receiver.play("spotify:track:abc")
    assert not isinstance(raised.value, ReceiverNotReady)


@pytest.mark.parametrize("status", [400, 404, 409, 503])
def test_other_http_errors_raise_receiver_error(status):
    receiver, _ = make((status, b""))
    with pytest.raises(ReceiverError, match=f"HTTP {status}"):
        receiver.play("spotify:track:abc")


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError(TimeoutError("timed out")),
        TimeoutError("timed out"),
        http.client.RemoteDisconnected("Remote end closed connection without response"),
        http.client.IncompleteRead(b"partial"),
        ConnectionResetError(104, "Connection reset by peer"),
    ],
)
@pytest.mark.parametrize("call", ["play", "pause", "resume", "status"])
def test_transport_errors_raise_receiver_error(error, call):
    receiver, _ = make(error)
    args = ("spotify:track:abc",) if call == "play" else ()
    with pytest.raises(ReceiverError):
        getattr(receiver, call)(*args)


def test_ready_true():
    receiver, fake = make((200, {"playback_ready": True}))
    assert receiver.ready() is True
    assert (fake.requests[0].method, fake.requests[0].url) == ("GET", f"{BASE}/")


@pytest.mark.parametrize(
    "reply",
    [
        REFUSED,
        TimeoutError("timed out"),
        (500, b""),
        (204, b""),
        (200, b"not json"),
        (200, {"playback_ready": False}),
        (200, {"playback_ready": "true"}),
        (200, b"[true]"),
    ],
)
def test_ready_false_on_error(reply):
    receiver, _ = make(reply)
    assert receiver.ready() is False
