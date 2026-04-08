"""Configuration reader for /boot/firmware/config.json (FAT32 boot partition)."""

import json
import logging
import os

logger = logging.getLogger(__name__)

CONFIG_SEARCH_PATHS = [
    "/boot/firmware/config.json",  # Pi OS Bookworm
    "/boot/config.json",           # Pi OS Bullseye and earlier
]


class Config:
    """Reads and provides typed access to the NFC-Player configuration."""

    def __init__(self, path=None):
        self.path = path or self._find_config()
        with open(self.path) as f:
            self._data = json.load(f)
        logger.info("Config loaded from %s", self.path)

    @staticmethod
    def _find_config():
        for p in CONFIG_SEARCH_PATHS:
            if os.path.exists(p):
                return p
        raise FileNotFoundError(
            "config.json not found. Searched: " + ", ".join(CONFIG_SEARCH_PATHS)
        )

    def reload(self):
        """Re-read config from disk (e.g. after user edits)."""
        with open(self.path) as f:
            self._data = json.load(f)
        logger.info("Config reloaded")

    # --- WiFi ---
    @property
    def wifi_networks(self):
        return self._data.get("wifi", [])

    # --- Bluetooth ---
    @property
    def bluetooth(self):
        return self._data.get("bluetooth", {})

    @property
    def speakers(self):
        """Return list of speakers sorted by priority (highest first).

        Supports both the new multi-speaker format and the legacy single-speaker
        format for backward compatibility.
        """
        bt = self.bluetooth
        if "speakers" in bt:
            speakers = list(bt["speakers"])
        elif "speaker_mac" in bt:
            speakers = [{
                "mac": bt["speaker_mac"],
                "name": bt.get("speaker_name", bt["speaker_mac"]),
                "priority": 10,
            }]
        else:
            return []
        return sorted(speakers, key=lambda s: s.get("priority", 0), reverse=True)

    @property
    def speaker_mac(self):
        """MAC of the highest-priority speaker (backward compat)."""
        speakers = self.speakers
        return speakers[0]["mac"] if speakers else ""

    @property
    def speaker_name(self):
        """Name of the highest-priority speaker (backward compat)."""
        speakers = self.speakers
        return speakers[0].get("name", "") if speakers else ""

    # --- Spotify ---
    @property
    def spotify(self):
        return self._data.get("spotify", {})

    @property
    def device_name(self):
        return self.spotify.get("device_name", "NFC-Box")

    @property
    def client_id(self):
        return self.spotify.get("client_id", "")

    @property
    def client_secret(self):
        return self.spotify.get("client_secret", "")

    @property
    def redirect_uri(self):
        return self.spotify.get("redirect_uri", "http://127.0.0.1:8888/callback")

    # --- NFC Tags ---
    @property
    def nfc_tags(self):
        return self._data.get("nfc_tags", {})

    # --- Behavior ---
    @property
    def pause_on_remove(self):
        return self._data.get("behavior", {}).get("pause_on_remove", False)

    # --- Spotify token cache ---
    @property
    def spotify_cache_path(self):
        """Return the path to the Spotify OAuth token cache file.

        Prefers the project-local cache (writable without sudo).
        Auto-migrates from boot partition on first use.
        """
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        local_cache = os.path.join(project_dir, "spotify_cache")

        # Prefer local (writable) cache
        if os.path.exists(local_cache):
            return local_cache

        # Migrate from boot partition if available
        for boot_path in ["/boot/firmware/spotify_cache", "/boot/spotify_cache"]:
            if os.path.exists(boot_path):
                try:
                    import shutil
                    shutil.copy2(boot_path, local_cache)
                    logger.info("Migrated spotify_cache from %s → %s", boot_path, local_cache)
                    return local_cache
                except (PermissionError, OSError):
                    return boot_path

        # Default: write to project directory
        return local_cache
