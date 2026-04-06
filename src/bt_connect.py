"""Bluetooth auto-connect service.

Continuously monitors the connection to the configured Bluetooth speaker
and reconnects when the link is lost.  Intended to run as a systemd service.
"""

import json
import logging
import subprocess
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [bt-connect] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

CONFIG_PATHS = ["/boot/firmware/config.json", "/boot/config.json"]
RETRY_INTERVAL = 5   # seconds between connection checks
SETTLE_TIME = 3       # seconds to wait after a connect attempt


def load_speaker_mac():
    for path in CONFIG_PATHS:
        try:
            with open(path) as f:
                return json.load(f)["bluetooth"]["speaker_mac"]
        except (FileNotFoundError, KeyError):
            continue
    logger.error("No config.json with bluetooth.speaker_mac found")
    sys.exit(1)


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=15)


def is_connected(mac):
    try:
        result = _run(["bluetoothctl", "info", mac])
        return "Connected: yes" in result.stdout
    except Exception:
        return False


def connect(mac):
    logger.info("Attempting connection to %s …", mac)
    _run(["bluetoothctl", "power", "on"])
    _run(["bluetoothctl", "connect", mac])
    time.sleep(SETTLE_TIME)


def ensure_trusted(mac):
    """Mark the device as trusted so BlueZ will accept it automatically."""
    _run(["bluetoothctl", "trust", mac])


def main():
    mac = load_speaker_mac()
    logger.info("Monitoring Bluetooth speaker %s", mac)
    ensure_trusted(mac)

    while True:
        if not is_connected(mac):
            connect(mac)
            if is_connected(mac):
                logger.info("✔ Connected to %s", mac)
            else:
                logger.warning("✖ Connection failed – retrying in %ds", RETRY_INTERVAL)
        time.sleep(RETRY_INTERVAL)


if __name__ == "__main__":
    main()
