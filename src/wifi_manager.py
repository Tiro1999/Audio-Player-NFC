"""WiFi manager – adds WiFi networks from NFC tags to config and NetworkManager."""

import hashlib
import json
import os
import subprocess
import tempfile

from .logger import Logger

logger = Logger(__name__)

CONFIG_PATHS = ["/boot/firmware/config.json", "/boot/config.json"]


def _find_config():
    for p in CONFIG_PATHS:
        if os.path.exists(p):
            return p
    return CONFIG_PATHS[0]


def _load_config():
    path = _find_config()
    try:
        with open(path) as f:
            return json.load(f), path
    except FileNotFoundError:
        return {}, path


def _save_config(data, path):
    """Save config.json – uses sudo cp fallback for boot partition."""
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except PermissionError:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
            json.dump(data, tmp, indent=2, ensure_ascii=False)
            tmp_path = tmp.name
        subprocess.run(["sudo", "cp", tmp_path, path], check=True)
        os.unlink(tmp_path)


def wpa_psk(ssid, password):
    """Derive WPA2 PSK hash (identical to wpa_passphrase)."""
    return hashlib.pbkdf2_hmac(
        "sha1", password.encode("utf-8"), ssid.encode("utf-8"), 4096, 32
    ).hex()


def handle_wifi_tag(wifi_data):
    """Process a WiFi NFC tag: add to config.json and apply to NetworkManager.

    Args:
        wifi_data: dict with keys: ssid, password, security, hidden

    Returns:
        True on success, False on failure.
    """
    ssid = wifi_data.get("ssid", "")
    password = wifi_data.get("password", "")
    security = wifi_data.get("security", "WPA").upper()

    if not ssid:
        logger.warn("WiFi tag has no SSID – ignoring")
        return False

    logger.info("📶 Processing WiFi tag: SSID='%s' Security=%s", ssid, security)

    # Hash password (unless open network)
    psk = ""
    if password and security not in ("", "NOPASS", "OPEN"):
        psk = wpa_psk(ssid, password)

    # ── Update config.json ────────────────────────────────────────────
    try:
        config_data, config_path = _load_config()

        if "wifi" not in config_data:
            config_data["wifi"] = []

        existing = next((w for w in config_data["wifi"] if w["ssid"] == ssid), None)
        if existing:
            if psk:
                existing["psk_hash"] = psk
                existing.pop("psk", None)
            existing["priority"] = existing.get("priority", 5)
            logger.info("Updated WiFi '%s' in config", ssid)
        else:
            entry = {"ssid": ssid, "priority": 5}
            if psk:
                entry["psk_hash"] = psk
            config_data["wifi"].append(entry)
            logger.info("Added WiFi '%s' to config", ssid)

        config_data["wifi"].sort(key=lambda w: w.get("priority", 0), reverse=True)
        _save_config(config_data, config_path)
    except Exception as exc:
        logger.error("Failed to update config.json: %s", exc)
        return False

    # ── Apply to NetworkManager ───────────────────────────────────────
    try:
        nm_psk = psk or password
        check = subprocess.run(
            ["nmcli", "connection", "show", ssid],
            capture_output=True,
        )

        if check.returncode == 0:
            cmd = [
                "sudo", "nmcli", "connection", "modify", ssid,
                "connection.autoconnect", "yes",
                "connection.autoconnect-priority", "5",
            ]
            if nm_psk:
                cmd += ["wifi-sec.psk", nm_psk]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error("nmcli modify failed: %s", result.stderr.strip())
                return False
            logger.info("Updated NM connection '%s'", ssid)
        else:
            cmd = [
                "sudo", "nmcli", "connection", "add",
                "type", "wifi", "con-name", ssid, "ssid", ssid,
                "connection.autoconnect", "yes",
                "connection.autoconnect-priority", "5",
            ]
            if nm_psk:
                cmd += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", nm_psk]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error("nmcli add failed: %s", result.stderr.strip())
                return False
            logger.info("Created NM connection '%s'", ssid)

        # Try to activate (may fail if network is out of range)
        result = subprocess.run(
            ["sudo", "nmcli", "connection", "up", ssid],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            logger.info("✅ WiFi '%s' connected!", ssid)
        else:
            logger.warn(
                "WiFi '%s' saved but not in range (will auto-connect later)", ssid
            )

        return True
    except Exception as exc:
        logger.error("Failed to apply WiFi to NetworkManager: %s", exc)
        return False
