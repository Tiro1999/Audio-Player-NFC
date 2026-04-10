"""Spotify playback control via the Spotify Web API (spotipy)."""

import os
import time

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from .logger import Logger
from .nfc_reader import is_valid_spotify_uri

logger = Logger(__name__)

SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing"


class SpotifyPlayer:
    """Thin wrapper around spotipy that targets a specific Spotify-Connect device."""

    def __init__(self, config):
        self.device_name = config.device_name
        cache_path = config.spotify_cache_path

        logger.info(
            "Spotify: client_id=%s…, device=%s, cache=%s",
            config.client_id[:8],
            self.device_name,
            cache_path,
        )

        self._sp = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=config.client_id,
                client_secret=config.client_secret,
                redirect_uri=config.redirect_uri,
                scope=SCOPES,
                cache_path=cache_path,
                open_browser=False,
            )
        )

        # Log the authenticated user
        try:
            user = self._sp.current_user()
            logger.info(
                "Spotify authenticated as: %s (%s)",
                user.get("display_name", "?"),
                user.get("id", "?"),
            )
        except Exception as exc:
            logger.warn("Could not verify Spotify auth: %s", exc)

    # ------------------------------------------------------------------
    # Device discovery
    # ------------------------------------------------------------------

    def _find_device_id(self):
        """Find the Raspotify / spotifyd device by name."""
        try:
            devices = self._sp.devices().get("devices", [])
        except Exception as exc:
            logger.error("Failed to query Spotify devices: %s", exc)
            return None

        if not devices:
            logger.debug("No Spotify devices available")
            return None

        names = [f"{d['name']} ({'active' if d['is_active'] else 'idle'})" for d in devices]
        logger.debug("Spotify devices: %s", " | ".join(names))

        for dev in devices:
            if dev["name"] == self.device_name:
                logger.info("Target device found: %s (id=%s…)", dev["name"], dev["id"][:12])
                return dev["id"]

        logger.warning(
            "Device '%s' not found. Available: %s",
            self.device_name,
            [d["name"] for d in devices],
        )
        return None

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def play(self, spotify_uri, retries=3, retry_delay=2):
        """
        Start playback of *spotify_uri* on the configured device.

        Rejects URIs that don't point to Spotify (security).
        Retries a few times if the device isn't found immediately (Raspotify
        may still be starting up).
        """
        logger.info("Playback request: %s", spotify_uri)

        if not is_valid_spotify_uri(spotify_uri):
            logger.error("URI rejected (not a valid Spotify link): %s", spotify_uri)
            return False

        for attempt in range(1, retries + 1):
            device_id = self._find_device_id()
            if device_id:
                break
            if attempt < retries:
                logger.info(
                    "Device not ready, retry %d/%d in %ds …",
                    attempt, retries, retry_delay,
                )
                time.sleep(retry_delay)
        else:
            logger.error("Could not find device '%s' after %d attempts", self.device_name, retries)
            return False

        try:
            uri_type = spotify_uri.split(":")[1] if spotify_uri.count(":") >= 2 else ""

            if uri_type in ("track", "episode", "chapter"):
                logger.debug("URI type '%s' → single item playback (uris=[])", uri_type)
                self._sp.start_playback(device_id=device_id, uris=[spotify_uri])
            elif uri_type in ("album", "playlist", "audiobook"):
                logger.debug("URI type '%s' → context playback (offset position=0)", uri_type)
                self._sp.start_playback(
                    device_id=device_id,
                    context_uri=spotify_uri,
                    offset={"position": 0},
                )
            else:
                logger.debug("URI type '%s' → context playback (no offset)", uri_type)
                self._sp.start_playback(device_id=device_id, context_uri=spotify_uri)

            logger.info("▶  Playing %s on %s", spotify_uri, self.device_name)
            return True
        except spotipy.exceptions.SpotifyException as exc:
            logger.error("Spotify API error: %s", exc)
            return False

    def pause(self):
        """Pause playback (best-effort)."""
        try:
            self._sp.pause_playback()
            logger.info("⏸  Paused")
        except Exception as exc:
            logger.trace("Pause failed (may already be paused): %s", exc)

    def resume(self):
        """Resume playback on the configured device."""
        device_id = self._find_device_id()
        if not device_id:
            return
        try:
            self._sp.start_playback(device_id=device_id)
            logger.info("▶  Resumed")
        except Exception as exc:
            logger.trace("Resume failed: %s", exc)

    def current_playback(self):
        """Return the current playback state dict (or None)."""
        try:
            return self._sp.current_playback()
        except Exception:
            return None
