"""Spotify playback control via the Spotify Web API (spotipy)."""

import logging
import os
import time

import spotipy
from spotipy.oauth2 import SpotifyOAuth

logger = logging.getLogger(__name__)

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

    # ------------------------------------------------------------------
    # Device discovery
    # ------------------------------------------------------------------

    def _find_device_id(self):
        """Find the Raspotify / spotifyd device by name."""
        try:
            devices = self._sp.devices().get("devices", [])
        except Exception as exc:
            logger.error("Failed to list Spotify devices: %s", exc)
            return None

        for dev in devices:
            if dev["name"] == self.device_name:
                return dev["id"]

        names = [d["name"] for d in devices]
        logger.warning(
            "Device '%s' not found. Available: %s", self.device_name, names
        )
        return None

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def play(self, spotify_uri, retries=3, retry_delay=2):
        """
        Start playback of *spotify_uri* on the configured device.

        Retries a few times if the device isn't found immediately (Raspotify
        may still be starting up).
        """
        for attempt in range(1, retries + 1):
            device_id = self._find_device_id()
            if device_id:
                break
            if attempt < retries:
                logger.info(
                    "Device not ready, retry %d/%d in %ds…",
                    attempt, retries, retry_delay,
                )
                time.sleep(retry_delay)
        else:
            logger.error("Could not find device '%s' after %d attempts", self.device_name, retries)
            return False

        try:
            if ":track:" in spotify_uri:
                self._sp.start_playback(device_id=device_id, uris=[spotify_uri])
            else:
                # album, playlist, artist, show, episode
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
            logger.debug("Pause failed (may already be paused): %s", exc)

    def resume(self):
        """Resume playback on the configured device."""
        device_id = self._find_device_id()
        if not device_id:
            return
        try:
            self._sp.start_playback(device_id=device_id)
            logger.info("▶  Resumed")
        except Exception as exc:
            logger.debug("Resume failed: %s", exc)

    def current_playback(self):
        """Return the current playback state dict (or None)."""
        try:
            return self._sp.current_playback()
        except Exception:
            return None
