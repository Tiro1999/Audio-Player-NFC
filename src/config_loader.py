"""Load application configuration from a JSON file on the boot partition.

The /boot partition of a Raspberry Pi is formatted as FAT32, meaning any
Windows or Mac PC can read and edit it without special tooling.  Users who
need to change WiFi credentials or Spotify settings therefore only need to
take the SD card out, edit ``/boot/config.json`` on their laptop and put it
back – no SSH required.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Locations searched in order; first existing file wins.
_DEFAULT_SEARCH_PATHS = [
    Path("/boot/config.json"),           # Raspberry Pi OS (legacy)
    Path("/boot/firmware/config.json"),  # Raspberry Pi OS Bookworm / Ubuntu
    Path(os.path.expanduser("~")) / "config.json",
    Path("config.json"),
]


def load_config(config_path: str | None = None) -> dict:
    """Return the configuration dictionary.

    Parameters
    ----------
    config_path:
        Explicit path to the JSON file.  When *None* the function searches
        :data:`_DEFAULT_SEARCH_PATHS` in order and returns the first match.

    Raises
    ------
    FileNotFoundError
        When no config file is found.
    ValueError
        When the config file exists but cannot be parsed as valid JSON.
    """
    paths_to_try = [Path(config_path)] if config_path else _DEFAULT_SEARCH_PATHS

    for path in paths_to_try:
        if path.exists():
            logger.info("Loading config from %s", path)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Config file {path} is not valid JSON: {exc}") from exc
            _validate_config(data)
            return data

    searched = [str(p) for p in paths_to_try]
    raise FileNotFoundError(
        "Config file not found. Searched: "
        + ", ".join(searched)
        + "\nPlease copy config.example.json to /boot/config.json and fill in your settings."
    )


def _validate_config(config: dict) -> None:
    """Raise *ValueError* for obviously missing required fields."""
    required_sections = ("wifi", "spotify", "bluetooth", "nfc")
    for section in required_sections:
        if section not in config:
            raise ValueError(f"Missing required section '{section}' in config.json")

    wifi_list = config.get("wifi", [])
    if not isinstance(wifi_list, list) or len(wifi_list) == 0:
        raise ValueError("'wifi' must be a non-empty list of network objects")

    spotify = config.get("spotify", {})
    for key in ("client_id", "client_secret", "device_name"):
        if not spotify.get(key):
            raise ValueError(f"Missing spotify.{key} in config.json")

    bluetooth = config.get("bluetooth", {})
    if not bluetooth.get("mac_address"):
        raise ValueError("Missing bluetooth.mac_address in config.json")
