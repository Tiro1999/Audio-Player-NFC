"""Main entry point for the NFC Audio Player.

Startup sequence
----------------
1. Load ``/boot/config.json``.
2. Start Bluetooth auto-reconnect loop.
3. Wait for the Spotify Connect device (Raspotify) to appear.
4. Enter the NFC polling loop:
   - Read tag → resolve Spotify URI → start playback.

Usage::

    python -m src.main
    # or via systemd: see setup/nfc-player.service
"""

import logging
import signal
import sys
import time

from .bluetooth_manager import BluetoothManager
from .config_loader import load_config
from .nfc_reader import NFCReader
from .spotify_controller import SpotifyController

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

_SPOTIFY_READY_TIMEOUT = 60   # seconds to wait for Raspotify to appear
_SPOTIFY_READY_POLL    = 5    # poll interval


def _wait_for_spotify_device(controller: SpotifyController, timeout: float) -> bool:
    """Block until the Spotify Connect device is visible or *timeout* expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if controller._find_device_id() is not None:  # noqa: SLF001
            return True
        logger.info("Waiting for Spotify device '%s'…", controller._device_name)  # noqa: SLF001
        time.sleep(_SPOTIFY_READY_POLL)
    return False


def run(config_path: str | None = None) -> None:
    """Load config and run the NFC polling loop (blocks until interrupted)."""
    config = load_config(config_path)

    # --- Bluetooth -----------------------------------------------------------
    bt_manager = BluetoothManager.from_config(config)
    bt_manager.trust()
    bt_manager.start_reconnect_loop()

    # --- Spotify -------------------------------------------------------------
    spotify = SpotifyController.from_config(config)
    if not _wait_for_spotify_device(spotify, _SPOTIFY_READY_TIMEOUT):
        logger.warning(
            "Spotify device not found after %ds – continuing anyway.",
            _SPOTIFY_READY_TIMEOUT,
        )

    # --- NFC -----------------------------------------------------------------
    tag_mappings = config.get("nfc", {}).get("tag_mappings", {})
    nfc = NFCReader(tag_mappings=tag_mappings)

    def _shutdown(signum, frame):  # noqa: ARG001
        logger.info("Shutting down…")
        bt_manager.stop_reconnect_loop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("NFC Audio Player ready – waiting for tags.")
    while True:
        try:
            uri = nfc.read_tag()
            if uri:
                logger.info("Playing: %s", uri)
                spotify.play(uri)
            time.sleep(0.1)
        except KeyboardInterrupt:
            _shutdown(None, None)
        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected error in main loop: %s", exc, exc_info=True)
            time.sleep(1)


if __name__ == "__main__":
    run()
