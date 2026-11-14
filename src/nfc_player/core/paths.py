"""On-device paths and fixed names. Every other module takes them from here."""

from pathlib import Path

BOOT_CONFIG = Path("/boot/firmware/config.json")  # master config, editable on the PC
DEVICE_CONFIG = Path("/etc/nfc-player/config.json")  # validated copy, last good version
UPDATE_TOKEN = Path("/etc/nfc-player/update-token")
STATE_DIR = Path("/var/lib/nfc-player")
RECEIVER_DIR = STATE_DIR / "receiver"
INSTALL_ROOT = Path("/opt/nfc-player")
SERVICE_USER = "nfc-player"
RECEIVER_API_URL = "http://127.0.0.1:3678"
WIFI_INTERFACE = "wlan0"
