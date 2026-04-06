"""NFC Spotify Player – main entry point.

Continuously reads NFC tags and triggers Spotify playback.
Run with:  python3 -m src.main
"""

import logging
import signal
import sys
import time

from .config import Config
from .nfc_reader import NFCReader
from .spotify_player import SpotifyPlayer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("nfc-player")

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logger.info("Received signal %d – shutting down …", signum)
    _shutdown = True


def main():
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # --- Load config ---
    config = Config()

    # --- Init hardware ---
    logger.info("Initializing NFC reader …")
    nfc = NFCReader()

    # --- Init Spotify ---
    logger.info("Connecting to Spotify API …")
    spotify = SpotifyPlayer(config)

    logger.info("NFC Player ready – waiting for tags …")

    last_uri = None

    while not _shutdown:
        try:
            uid = nfc.wait_for_tag(timeout=0.5)
            if uid is None:
                # No tag present
                time.sleep(0.1)
                continue

            logger.info("Tag detected: %s", uid)

            uri = nfc.read_spotify_uri(uid, config.nfc_tags)
            if uri is None:
                logger.warning("Unknown tag %s – ignoring", uid)
                nfc.wait_for_removal()
                last_uri = None
                continue

            # Only start playback if it's a new URI
            if uri != last_uri:
                spotify.play(uri)
                last_uri = uri
            else:
                logger.info("Same tag – playback continues")

            # Wait until the tag is removed
            nfc.wait_for_removal()
            logger.info("Tag removed")

            if config.pause_on_remove:
                spotify.pause()
                last_uri = None

        except KeyboardInterrupt:
            break
        except Exception as exc:
            logger.error("Unexpected error: %s", exc, exc_info=True)
            time.sleep(2)

    logger.info("Goodbye!")


if __name__ == "__main__":
    main()
