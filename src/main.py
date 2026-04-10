"""NFC Spotify Player – main entry point.

Continuously reads NFC tags and triggers Spotify playback.
Supports WiFi configuration via NFC tags.
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


def _handle_wifi_tag(tag_data):
    """Process a WiFi NFC tag – add network and connect."""
    try:
        from .wifi_manager import handle_wifi_tag
        handle_wifi_tag(tag_data)
    except Exception as exc:
        logger.error("WiFi tag handling failed: %s", exc)


def main():
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    config = Config()

    logger.info("══════════════════════════════════════════")
    logger.info("  NFC Spotify Player – Starting")
    logger.info("══════════════════════════════════════════")

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

    logger.info("══════════════════════════════════════════")
    logger.info("  ✅ Ready – waiting for NFC tags")
    logger.info("══════════════════════════════════════════")

    last_uri = None

    while not _shutdown:
        try:
            uid = nfc.wait_for_tag(timeout=0.5)
            if uid is None:
                time.sleep(0.1)
                continue

            # ── Tag lifecycle ─────────────────────────────────────
            logger.info("──── Tag detected ──────────────────────")
            logger.info("  UID    : %s", uid)

            tag_data = nfc.read_tag(uid, config.nfc_tags)
            if tag_data is None:
                logger.warn("  Result : No actionable data (unknown tag)")
                logger.info("  Waiting for tag removal …")
                nfc.wait_for_removal()
                last_uri = None
                logger.info("  Tag removed")
                time.sleep(REMOVAL_COOLDOWN)
                logger.info("────────────────────────────────────────")
                continue

            # ── WiFi tag ──
            if tag_data["type"] == "wifi":
                logger.info("  Type   : WiFi")
                logger.info("  SSID   : %s", tag_data.get("ssid", "?"))
                logger.info("  Security: %s", tag_data.get("security", "?"))
                logger.info("  Action : Configuring network …")
                _handle_wifi_tag(tag_data)
                logger.info("  Waiting for tag removal …")
                nfc.wait_for_removal()
                logger.info("  Tag removed")
                time.sleep(REMOVAL_COOLDOWN)
                logger.info("────────────────────────────────────────")
                continue

            # ── Spotify tag ──
            uri = tag_data["uri"]
            logger.info("  Type   : Spotify")
            logger.info("  URI    : %s", uri)

            if uri != last_uri:
                logger.info("  Action : New URI → starting playback")
                result = spotify.play(uri)
                if result:
                    logger.info("  Result : ✅ Playback started")
                else:
                    logger.error("  Result : ❌ Playback failed")
                last_uri = uri
            else:
                logger.info("  Action : Same tag re-scanned → playback continues")

            logger.info("  Waiting for tag removal …")
            nfc.wait_for_removal()
            logger.info("  Tag removed")
            last_uri = None  # allow re-scan of same tag
            time.sleep(REMOVAL_COOLDOWN)

            if config.pause_on_remove:
                logger.info("  Pausing playback (pause_on_remove=true)")
                spotify.pause()

            logger.info("────────────────────────────────────────")

        except OSError as exc:
            logger.error("I2C bus error: %s", exc)
            logger.info("Reinitializing NFC reader …")
            nfc = _init_nfc()
            if nfc is None:
                while nfc is None and not _shutdown:
                    logger.info("NFC hardware unavailable – retry in %ds", NFC_RETRY_INTERVAL)
                    time.sleep(NFC_RETRY_INTERVAL)
                    nfc = _init_nfc()
            time.sleep(1)
        except KeyboardInterrupt:
            break
        except Exception as exc:
            logger.error("Unexpected error: %s", exc, exc_info=True)
            time.sleep(2)

    logger.info("Goodbye!")


if __name__ == "__main__":
    main()
