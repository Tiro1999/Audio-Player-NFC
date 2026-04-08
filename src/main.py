"""NFC Spotify Player – main entry point.

Continuously reads NFC tags and triggers Spotify playback.
Run with:  python3 -m src.main
"""

import signal
import sys
import time

from .config import Config
from .logger import Logger

logger = Logger("nfc-player")

_shutdown = False

NFC_RETRY_INTERVAL = 10  # seconds between NFC init retries
REMOVAL_COOLDOWN = 1.5   # seconds after tag removal before accepting a new tag


def _handle_signal(signum, frame):
    global _shutdown
    logger.info("Received signal %d – shutting down …", signum)
    _shutdown = True


def _init_nfc():
    """Try to initialise the NFC reader, return None if hardware is missing."""
    try:
        from .nfc_reader import NFCReader
        reader = NFCReader()
        logger.info("NFC reader initialised successfully")
        return reader
    except Exception as exc:
        logger.warn("NFC reader not available: %s", exc)
        return None


def _init_spotify(config):
    """Try to initialise the Spotify player, return None on failure."""
    try:
        from .spotify_player import SpotifyPlayer
        player = SpotifyPlayer(config)
        logger.info("Spotify player ready")
        return player
    except Exception as exc:
        logger.warn("Spotify init failed: %s", exc)
        return None


def main():
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    config = Config()

    # --- Wait for NFC reader hardware ---
    logger.info("Initializing NFC reader …")
    nfc = _init_nfc()
    while nfc is None and not _shutdown:
        logger.info("Retrying NFC init in %ds … (is the PN532 connected?)", NFC_RETRY_INTERVAL)
        time.sleep(NFC_RETRY_INTERVAL)
        nfc = _init_nfc()

    if _shutdown:
        return

    # --- Init Spotify (retry until available) ---
    logger.info("Connecting to Spotify API …")
    spotify = _init_spotify(config)
    while spotify is None and not _shutdown:
        logger.info("Retrying Spotify init in %ds …", NFC_RETRY_INTERVAL)
        time.sleep(NFC_RETRY_INTERVAL)
        spotify = _init_spotify(config)

    if _shutdown:
        return

    logger.info("NFC Player ready – waiting for tags …")

    last_uri = None

    while not _shutdown:
        try:
            uid = nfc.wait_for_tag(timeout=0.5)
            if uid is None:
                time.sleep(0.1)
                continue

            logger.info("Tag detected: %s", uid)

            uri = nfc.read_spotify_uri(uid, config.nfc_tags)
            if uri is None:
                logger.warn("Unknown tag %s – ignoring", uid)
                nfc.wait_for_removal()
                last_uri = None
                time.sleep(REMOVAL_COOLDOWN)
                continue

            if uri != last_uri:
                spotify.play(uri)
                last_uri = uri
            else:
                logger.info("Same tag – playback continues")

            nfc.wait_for_removal()
            logger.info("Tag removed")
            time.sleep(REMOVAL_COOLDOWN)

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
