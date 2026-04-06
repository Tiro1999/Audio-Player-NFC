"""Spotify playback controller.

Uses the *spotipy* library with the Authorization Code flow so that the
application can both read the user's currently active devices and start /
resume playback on a specific Spotify Connect device (e.g. Raspotify running
on the same Raspberry Pi).

OAuth token caching
-------------------
On first run the user must complete the browser-based OAuth flow once
(``setup/install.sh`` opens the URL automatically).  After that *spotipy*
stores the token in ``~/.spotify_token_cache`` and refreshes it silently.

Raspotify
---------
The ``nfc-player.service`` systemd unit depends on ``raspotify.service`` so
the Spotify Connect receiver is already running when this module starts.
The device is identified by ``spotify.device_name`` in ``config.json``.
"""

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

_SCOPE = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-currently-playing"
)
_TOKEN_CACHE_PATH = "/home/pi/.spotify_token_cache"


class SpotifyController:
    """Control Spotify playback via the Web API.

    Parameters
    ----------
    client_id:
        Spotify application client ID.
    client_secret:
        Spotify application client secret.
    redirect_uri:
        OAuth redirect URI (must match the Spotify app settings).
    device_name:
        Name of the Spotify Connect device to target (Raspotify device name).
    token_cache_path:
        Path where *spotipy* stores the cached OAuth token.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        device_name: str,
        token_cache_path: str = _TOKEN_CACHE_PATH,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._device_name = device_name
        self._token_cache_path = token_cache_path
        self._sp = None  # spotipy.Spotify instance, created lazily

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self):
        """Return an authenticated *spotipy.Spotify* instance (lazy init)."""
        if self._sp is None:
            import spotipy  # type: ignore[import]
            from spotipy.oauth2 import SpotifyOAuth  # type: ignore[import]

            auth_manager = SpotifyOAuth(
                client_id=self._client_id,
                client_secret=self._client_secret,
                redirect_uri=self._redirect_uri,
                scope=_SCOPE,
                cache_path=self._token_cache_path,
                open_browser=False,
            )
            self._sp = spotipy.Spotify(auth_manager=auth_manager)
        return self._sp

    def _find_device_id(self) -> Optional[str]:
        """Return the Spotify Connect device ID matching *device_name*."""
        sp = self._get_client()
        try:
            devices = sp.devices().get("devices", [])
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not fetch Spotify devices: %s", exc)
            return None

        for device in devices:
            if device.get("name", "").lower() == self._device_name.lower():
                return device["id"]

        available = [d.get("name") for d in devices]
        logger.warning(
            "Device '%s' not found. Available devices: %s",
            self._device_name,
            available,
        )
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def play(self, spotify_uri: str, retries: int = 3, retry_delay: float = 2.0) -> bool:
        """Start playback of *spotify_uri* on the configured device.

        Retries *retries* times if the device is not yet visible (e.g. Raspotify
        is still starting up).

        Parameters
        ----------
        spotify_uri:
            A Spotify URI such as ``spotify:playlist:37i9dQZF1DXcBWIGoYBM5M``
            or ``spotify:track:4uLU6hMCjMI75M1A2tKUQC``.
        retries:
            Number of retry attempts if the target device is not found.
        retry_delay:
            Seconds to wait between retries.

        Returns
        -------
        bool
            *True* if playback started successfully, *False* otherwise.
        """
        sp = self._get_client()

        for attempt in range(1, retries + 1):
            device_id = self._find_device_id()
            if device_id:
                break
            logger.info(
                "Device not found (attempt %d/%d), retrying in %.1fs…",
                attempt,
                retries,
                retry_delay,
            )
            time.sleep(retry_delay)
        else:
            logger.error(
                "Device '%s' unavailable after %d attempts – playback aborted.",
                self._device_name,
                retries,
            )
            return False

        uri_type = spotify_uri.split(":")[1] if ":" in spotify_uri else ""
        try:
            if uri_type == "track":
                sp.start_playback(device_id=device_id, uris=[spotify_uri])
            else:
                sp.start_playback(device_id=device_id, context_uri=spotify_uri)
            logger.info("Playback started: %s on device %s", spotify_uri, self._device_name)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to start playback: %s", exc)
            return False

    def pause(self) -> bool:
        """Pause playback on the configured device.

        Returns *True* on success.
        """
        sp = self._get_client()
        device_id = self._find_device_id()
        if not device_id:
            return False
        try:
            sp.pause_playback(device_id=device_id)
            logger.info("Playback paused on device %s", self._device_name)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to pause playback: %s", exc)
            return False

    def is_playing(self) -> bool:
        """Return *True* if the configured device is currently playing."""
        sp = self._get_client()
        try:
            pb = sp.current_playback()
            if pb and pb.get("is_playing") and pb.get("device"):
                return pb["device"].get("name", "").lower() == self._device_name.lower()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not get playback state: %s", exc)
        return False

    @classmethod
    def from_config(cls, config: dict) -> "SpotifyController":
        """Construct a :class:`SpotifyController` from the app config dict."""
        sp_cfg = config["spotify"]
        return cls(
            client_id=sp_cfg["client_id"],
            client_secret=sp_cfg["client_secret"],
            redirect_uri=sp_cfg.get("redirect_uri", "http://localhost:8888/callback"),
            device_name=sp_cfg["device_name"],
        )
