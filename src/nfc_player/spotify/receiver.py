"""Receiver control over go-librespot's local HTTP API (127.0.0.1, no auth).

Every failure becomes a ReceiverError, so a receiver that is offline or still starting
costs one failed call, never a crash.
"""

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPException
from typing import Any

from nfc_player.core.config import DEFAULT_DEVICE_NAME
from nfc_player.core.paths import RECEIVER_API_URL

log = logging.getLogger(__name__)

_NO_SESSION = 204  # go-librespot answers 204 until the receiver has a Spotify session
_MAX_BODY = 64 * 1024


class ReceiverError(Exception):
    """The receiver did not carry out a request."""


class ReceiverNotReady(ReceiverError):
    """The receiver has no Spotify session yet: the one-time pairing in the Spotify app is missing."""


@dataclass(frozen=True)
class ReceiverStatus:
    stopped: bool
    paused: bool


class Receiver:
    """Client of the receiver API. `device_name` only appears in the pairing hint of ReceiverNotReady."""

    def __init__(
        self,
        base_url: str = RECEIVER_API_URL,
        *,
        timeout: float = 5.0,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
        device_name: str = DEFAULT_DEVICE_NAME,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._urlopen = urlopen
        self._device_name = device_name

    def play(self, uri: str) -> None:
        """Play `uri` from the start. The shuffle state stays as it is."""
        self._command("/player/play", {"uri": uri})

    def pause(self) -> None:
        self._command("/player/pause")

    def resume(self) -> None:
        self._command("/player/resume")

    def status(self) -> ReceiverStatus:
        """Playback state; without a Spotify session the receiver counts as stopped."""
        code, body = self._request("GET", "/status")
        if code == _NO_SESSION:
            return ReceiverStatus(stopped=True, paused=False)
        data = _json_object(body)
        stopped, paused = data.get("stopped"), data.get("paused")
        if not isinstance(stopped, bool) or not isinstance(paused, bool):
            raise ReceiverError("the receiver sent a status without stopped and paused")
        return ReceiverStatus(stopped=stopped, paused=paused)

    def ready(self) -> bool:
        """True if the receiver can play now (playback_ready); False on any error."""
        try:
            code, body = self._request("GET", "/")
            return code != _NO_SESSION and _json_object(body).get("playback_ready") is True
        except ReceiverError:
            return False

    def _command(self, path: str, payload: dict[str, str] | None = None) -> None:
        code, _ = self._request("POST", path, payload)
        if code == _NO_SESSION:
            # NAMING-CHECK: "WLAN" is the given hint text; the project's English term is "WiFi".
            raise ReceiverNotReady(
                f"the receiver has no Spotify session yet: select '{self._device_name}' "
                "once in the Spotify app on the same WLAN"
            )

    def _request(self, method: str, path: str, payload: dict[str, str] | None = None) -> tuple[int, bytes]:
        """(status, body) of a 2xx answer; anything else raises ReceiverError."""
        data = None if payload is None else json.dumps(payload).encode()
        # S310: the URL is base_url (our fixed http API URL) plus a constant path.
        request = urllib.request.Request(self._base_url + path, data=data, method=method)  # noqa: S310
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with self._urlopen(request, timeout=self._timeout) as response:
                code, body = response.status, response.read(_MAX_BODY)
        except urllib.error.HTTPError as exc:
            exc.close()
            raise ReceiverError(f"the receiver answered {method} {path} with HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ReceiverError(f"the receiver is not reachable: {exc.reason}") from exc
        except (OSError, HTTPException) as exc:  # timeouts and dropped connections after connecting
            raise ReceiverError(f"no answer from the receiver to {method} {path}: {exc}") from exc
        log.debug("%s %s: HTTP %d", method, path, code)
        return code, body


def _json_object(body: bytes) -> dict[str, Any]:
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):  # ValueError includes invalid UTF-8
        data = None
    if not isinstance(data, dict):
        raise ReceiverError("the receiver sent no valid JSON object")
    return data
