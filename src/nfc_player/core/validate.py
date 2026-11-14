"""Validation of external input: config, tags and CLI arguments.

The *_error functions return a message or None; the normalize_* functions raise ValueError.
Messages never contain the checked value, so callers may log them.
"""

import re
from typing import Any

PLACEHOLDER_MACS = frozenset({"AA:BB:CC:DD:EE:FF", "00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"})
SECURITIES = ("wpa-psk", "sae", "open")

_MAC = re.compile(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}")
_HEX64 = re.compile(r"[0-9A-Fa-f]{64}")
_UID = re.compile(r"[0-9A-F]{8,20}")
_UID_SEPARATORS = str.maketrans("", "", " :-")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_REPO_PREFIXES = ("git@github.com:", "https://github.com/", "http://github.com/")


def _utf8_size(text: str) -> int | None:
    """Length in UTF-8 bytes; None if the text cannot be encoded (lone surrogates)."""
    try:
        return len(text.encode("utf-8"))
    except UnicodeEncodeError:
        return None


def _has_control_chars(text: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in text)


def ssid_error(ssid: str) -> str | None:
    """1..32 UTF-8 bytes without control characters."""
    if not isinstance(ssid, str):
        return "SSID must be text"
    size = _utf8_size(ssid)
    if size is None:
        return "SSID is not valid UTF-8"
    if not 1 <= size <= 32:
        return "SSID must be 1..32 bytes long"
    if _has_control_chars(ssid):
        return "SSID must not contain control characters"
    return None


def is_psk_hash(value: Any) -> bool:
    """True for exactly 64 hex digits, a precomputed WPA-PSK."""
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


def passphrase_error(secret: str, security: str) -> str | None:
    """Check a WiFi password against its security type (see SECURITIES)."""
    if not isinstance(secret, str):
        return "password must be text"
    if security == "wpa-psk":
        if len(secret) == 64:
            return None if is_psk_hash(secret) else "a 64-character WPA key must be hex"
        if 8 <= len(secret) <= 63 and all(" " <= char <= "~" for char in secret):
            return None
        return "WPA password must be 8..63 printable ASCII characters"
    if security == "sae":
        if 1 <= len(secret) <= 128 and _utf8_size(secret) is not None and not _has_control_chars(secret):
            return None
        return "WPA3 password must be 1..128 characters without control characters"
    if security == "open":
        return "an open network takes no password" if secret else None
    return "security must be wpa-psk, sae or open"


def normalize_mac(mac: str) -> str:
    """Upper-case MAC address; ValueError unless it looks like AA:BB:CC:DD:EE:FF."""
    if isinstance(mac, str) and mac.isascii() and _MAC.fullmatch(mac.upper()):
        return mac.upper()
    raise ValueError("MAC address must look like AA:BB:CC:DD:EE:FF")


def normalize_uid(uid: str) -> str:
    """Tag UID without " :-" separators in upper case; ValueError unless 8..20 hex digits."""
    if isinstance(uid, str) and uid.isascii():
        cleaned = uid.translate(_UID_SEPARATORS).upper()
        if _UID.fullmatch(cleaned):
            return cleaned
    raise ValueError("tag UID must be 8..20 hex digits")


def device_name_error(name: str) -> str | None:
    """Receiver name: 1..64 printable characters without quotes, backslash or newline."""
    if not isinstance(name, str):
        return "device name must be text"
    if not 1 <= len(name) <= 64:
        return "device name must be 1..64 characters long"
    if not name.isprintable() or any(char in "\"'\\\n" for char in name):
        return "device name must be printable, without quotes or backslashes"
    return None


def speaker_name_error(name: str) -> str | None:
    """Speaker name: 1..64 characters without control characters."""
    if not isinstance(name, str):
        return "speaker name must be text"
    if not 1 <= len(name) <= 64:
        return "speaker name must be 1..64 characters long"
    if _has_control_chars(name):
        return "speaker name must not contain control characters"
    return None


def normalize_repo(repo: str) -> str:
    """'owner/name' from 'owner/name' or a GitHub https, http or SSH URL; ValueError otherwise."""
    if isinstance(repo, str) and repo.isascii():
        text = repo.strip()
        for prefix in _REPO_PREFIXES:
            if text.lower().startswith(prefix):
                text = text[len(prefix) :]
                break
        text = text.rstrip("/").removesuffix(".git")
        # "." or ".." would walk up the path of the GitHub API URL.
        if _REPO.fullmatch(text) and not {".", ".."} & set(text.split("/")):
            return text
    raise ValueError("github_repo must be owner/name or a GitHub URL")
