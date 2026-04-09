#!/usr/bin/env python3
# --- Auto-activate project venv if available ---
import os, sys
_venv_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "venv")
_venv_py = os.path.join(_venv_dir, "bin", "python3")
if os.path.isfile(_venv_py) and sys.prefix == sys.base_prefix:
    os.execv(_venv_py, [_venv_py] + sys.argv)
# -----------------------------------------------
"""Simulate an NFC tag read – test the full Spotify flow without hardware.

Usage (on the Pi via SSH):

    python3 ~/nfc-player/tools/nfc_test.py "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
    python3 ~/nfc-player/tools/nfc_test.py "spotify:track:6rqhFgbbKwnb9MLmUQDhG6"
    python3 ~/nfc-player/tools/nfc_test.py "spotify:album:6dVIqQ8qmQ5GBnJ9shOYGE"

This injects a Spotify URI directly into the player, bypassing the NFC reader.
Useful for testing while the PN532 module hasn't arrived yet.
"""

import argparse

# Add project root to path so we can import src.*
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from src.config import Config
from src.logger import Logger
from src.nfc_reader import is_valid_spotify_uri, spotify_url_to_uri
from src.spotify_player import SpotifyPlayer

logger = Logger("nfc-test")


def main():
    parser = argparse.ArgumentParser(
        description="Inject a Spotify URI (simulates NFC tag read)",
    )
    parser.add_argument(
        "uri",
        help="Spotify URI or URL, e.g. spotify:playlist:xxx or https://open.spotify.com/…",
    )
    args = parser.parse_args()

    raw_uri = args.uri

    # ── Convert URL → native URI if needed ─────────────────────────────
    uri = spotify_url_to_uri(raw_uri) or raw_uri

    # ── Validate ───────────────────────────────────────────────────────
    if not is_valid_spotify_uri(uri):
        logger.error("Not a valid Spotify URI: %s", raw_uri)
        print("\nExamples of valid URIs:")
        print("  spotify:track:6rqhFgbbKwnb9MLmUQDhG6")
        print("  spotify:playlist:37i9dQZF1DXcBWIGoYBM5M")
        print("  https://open.spotify.com/album/xyz")
        sys.exit(1)

    logger.info("🏷️   Injected URI: %s", uri)

    # ── Load config ────────────────────────────────────────────────────
    try:
        config = Config()
        logger.info("Config loaded from %s", config.path)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        print("\n→ Create /boot/firmware/config.json first (see config.json.example)")
        sys.exit(1)

    # ── Init Spotify ───────────────────────────────────────────────────
    try:
        spotify = SpotifyPlayer(config)
    except Exception as exc:
        logger.error("Spotify init failed: %s", exc)
        print("\n→ Check spotify section in config.json")
        print("→ Make sure /boot/firmware/spotify_cache exists (run tools/spotify_auth.py)")
        sys.exit(1)

    # ── Play ───────────────────────────────────────────────────────────
    success = spotify.play(uri)
    if success:
        logger.info("✅  Playback started!")
    else:
        logger.error("Playback failed – check: tail -f /var/log/nfc_player.log")
        sys.exit(1)


if __name__ == "__main__":
    main()
