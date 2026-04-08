"""Bluetooth auto-connect service.

Continuously monitors the connection to configured Bluetooth speakers
and reconnects when the link is lost.  Supports multiple speakers with
priority (highest priority wins).  Runs as a systemd service.
"""

import json
import os
import re
import subprocess
import sys
import time

from .logger import Logger

logger = Logger(__name__)

CONFIG_PATHS = ["/boot/firmware/config.json", "/boot/config.json"]
RETRY_INTERVAL = 5   # seconds between connection checks
SETTLE_TIME = 3       # seconds to wait after a connect attempt
CONFIG_RELOAD_INTERVAL = 60  # re-read config every N seconds

_PLACEHOLDER_MACS = {"AA:BB:CC:DD:EE:FF", "00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"}


def _is_valid_mac(mac):
    """Return True if mac is a real (non-placeholder) BT address."""
    if not re.match(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$", mac):
        return False
    return mac.upper() not in _PLACEHOLDER_MACS


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
        return []

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

    # Filter out placeholder/invalid MACs
    valid = [s for s in speakers if _is_valid_mac(s.get("mac", ""))]
    skipped = len(speakers) - len(valid)
    if skipped > 0:
        logger.debug("Skipped %d placeholder speaker(s)", skipped)

    return sorted(valid, key=lambda s: s.get("priority", 0), reverse=True)


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=15)


def is_connected(mac):
    try:
        result = _run(["bluetoothctl", "info", mac])
        return "Connected: yes" in result.stdout
    except Exception:
        return False


def _ensure_bt_ready():
    """Unblock and power on the Bluetooth adapter."""
    subprocess.run(["sudo", "rfkill", "unblock", "bluetooth"], capture_output=True)
    time.sleep(0.5)
    _run(["bluetoothctl", "power", "on"])


def connect(mac):
    logger.info("Attempting connection to %s", mac)
    _ensure_bt_ready()
    _run(["bluetoothctl", "connect", mac])
    time.sleep(SETTLE_TIME)


def ensure_trusted(mac):
    """Mark the device as trusted so BlueZ will accept it automatically."""
    _run(["bluetoothctl", "trust", mac])


def main():
    speakers = load_speakers()

    # Ensure BT adapter is ready before doing anything
    _ensure_bt_ready()

    if speakers:
        logger.info("Configured speakers (by priority):")
        for s in speakers:
            logger.info("  [prio %d] %s (%s)", s.get("priority", 0), s.get("name", "?"), s["mac"])
        for s in speakers:
            ensure_trusted(s["mac"])
    else:
        logger.info("No valid speakers configured – waiting for config update …")

    connected_mac = None
    connected_name = None
    last_config_load = time.time()

    while True:
        # Periodically reload config to pick up new speakers added via bt_tools
        if time.time() - last_config_load > CONFIG_RELOAD_INTERVAL:
            new_speakers = load_speakers()
            if new_speakers != speakers:
                speakers = new_speakers
                logger.info("Config reloaded – %d speaker(s)", len(speakers))
                for s in speakers:
                    ensure_trusted(s["mac"])
            last_config_load = time.time()

        if not speakers:
            time.sleep(RETRY_INTERVAL)
            continue

        # If currently connected, just monitor
        if connected_mac and is_connected(connected_mac):
            time.sleep(RETRY_INTERVAL)
            continue

        if connected_mac:
            logger.warn("Lost connection to %s (%s)", connected_name, connected_mac)
            connected_mac = None
            connected_name = None

        # Try speakers in priority order
        for speaker in speakers:
            mac = speaker["mac"]
            name = speaker.get("name", mac)
            prio = speaker.get("priority", 0)
            logger.info("Trying %s (%s, prio %d)", name, mac, prio)

            connect(mac)

            if is_connected(mac):
                logger.info("Connected to %s (%s)", name, mac)
                connected_mac = mac
                connected_name = name
                break
        else:
            logger.debug("No speakers available – retrying in %ds", RETRY_INTERVAL)

        time.sleep(RETRY_INTERVAL)


if __name__ == "__main__":
    main()
