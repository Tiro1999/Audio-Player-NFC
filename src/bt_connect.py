"""Bluetooth auto-connect service.

Continuously monitors the connection to configured Bluetooth speakers
and reconnects when the link is lost.  Supports multiple speakers with
priority (highest priority wins).  Runs as a systemd service.
"""

import json
import logging
import os
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


def load_speakers():
    """Load speakers from config.json, sorted by priority (highest first)."""
    for path in CONFIG_PATHS:
        try:
            with open(path) as f:
                bt = json.load(f).get("bluetooth", {})
                break
        except (FileNotFoundError, KeyError):
            continue
    else:
        logger.error("No config.json with bluetooth section found")
        sys.exit(1)

    # Support both multi-speaker and legacy single-speaker format
    if "speakers" in bt:
        speakers = list(bt["speakers"])
    elif "speaker_mac" in bt:
        speakers = [{
            "mac": bt["speaker_mac"],
            "name": bt.get("speaker_name", bt["speaker_mac"]),
            "priority": 10,
        }]
    else:
        logger.error("No speakers configured in config.json")
        sys.exit(1)

    return sorted(speakers, key=lambda s: s.get("priority", 0), reverse=True)


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
    speakers = load_speakers()

    logger.info("Configured speakers (by priority):")
    for s in speakers:
        logger.info("  [prio %d] %s (%s)", s.get("priority", 0), s.get("name", "?"), s["mac"])

    for s in speakers:
        ensure_trusted(s["mac"])

    connected_mac = None
    connected_name = None

    while True:
        # If currently connected, just monitor
        if connected_mac and is_connected(connected_mac):
            time.sleep(RETRY_INTERVAL)
            continue

        if connected_mac:
            logger.warning("Lost connection to %s (%s)", connected_name, connected_mac)
            connected_mac = None
            connected_name = None

        # Try speakers in priority order
        for speaker in speakers:
            mac = speaker["mac"]
            name = speaker.get("name", mac)
            prio = speaker.get("priority", 0)
            logger.info("Trying %s (%s, prio %d) …", name, mac, prio)

            connect(mac)

            if is_connected(mac):
                logger.info("✔ Connected to %s (%s)", name, mac)
                connected_mac = mac
                connected_name = name
                break
        else:
            logger.warning("No speakers available – retrying in %ds", RETRY_INTERVAL)

        time.sleep(RETRY_INTERVAL)


if __name__ == "__main__":
    main()
