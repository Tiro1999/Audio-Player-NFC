"""Config: validated loading of config.json, atomic writes and raw-dict edits for the CLIs.

parse_config raises ConfigError listing every error; an invalid entry is skipped with a warning.
"""

import contextlib
import copy
import json
import os
import re
import tempfile
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from nfc_player.core.validate import (
    PLACEHOLDER_MACS,
    SECURITIES,
    device_name_error,
    is_psk_hash,
    normalize_mac,
    normalize_repo,
    normalize_uid,
    passphrase_error,
    speaker_name_error,
    ssid_error,
)

DEFAULT_DEVICE_NAME = "NFC-Box"

_NOT_AN_OBJECT = "the top level must be a JSON object"
_WEB_API_KEYS = ("client_id", "client_secret", "redirect_uri")
_GITHUB_TOKEN = re.compile(r"[!-~]+")  # printable ASCII without spaces: safe in an HTTP header


class ConfigError(ValueError):
    """The config is unusable; `problems` lists every error found."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class WifiSeed:
    """A WiFi entry of the config; without secret and security it only sets the priority."""

    ssid: str
    priority: int = 5
    secret: str | None = field(default=None, repr=False)
    security: str | None = None
    hidden: bool = False


@dataclass(frozen=True)
class Speaker:
    mac: str
    name: str
    priority: int


@dataclass(frozen=True)
class Config:
    wifi: tuple[WifiSeed, ...] = ()
    speakers: tuple[Speaker, ...] = ()
    device_name: str = DEFAULT_DEVICE_NAME
    # A factory: Python 3.11 rejects an unhashable mappingproxy as a plain default.
    nfc_tags: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    pause_on_remove: bool = False
    wifi_tags: bool = True
    auto_update: bool = False
    github_repo: str = ""
    update_token: str | None = field(default=None, repr=False)
    warnings: tuple[str, ...] = ()


# --- Reading and validation ---


def read_raw(path: Path) -> dict[str, Any]:
    """Read a config file as a dict; a UTF-8 BOM and CRLF are fine. Missing file → FileNotFoundError."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError:
        raise ConfigError(["the file is not UTF-8 text"]) from None
    except json.JSONDecodeError as exc:
        # Position and reason only: the document may hold secrets.
        raise ConfigError([f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"]) from None
    if not isinstance(raw, dict):
        raise ConfigError([_NOT_AN_OBJECT])
    return raw


def load_config(path: Path) -> Config:
    return parse_config(read_raw(path))


def parse_config(raw: Mapping[str, Any]) -> Config:
    """Validate a raw config. Raises ConfigError listing every error; skipped entries become warnings."""
    if not isinstance(raw, Mapping):
        raise ConfigError([_NOT_AN_OBJECT])
    problems: list[str] = []
    warnings: list[str] = []
    wifi = _wifi_seeds(_section(raw, "wifi", list, problems), problems, warnings)
    speakers = _speakers(_section(raw, "bluetooth", Mapping, problems), problems, warnings)
    device_name = _spotify(_section(raw, "spotify", Mapping, problems), problems, warnings)
    behavior = _section(raw, "behavior", Mapping, problems)
    flags = {key: _flag(behavior, key, "behavior", problems) for key in behavior}
    update = _section(raw, "update", Mapping, problems)
    auto_update = _flag(update, "auto_update", "update", problems)
    github_repo = _github_repo(update, warnings)
    update_token = _update_token(update, warnings)
    nfc_tags = _nfc_tags(_section(raw, "nfc_tags", Mapping, problems), warnings)
    if problems:
        raise ConfigError(problems)
    return Config(
        wifi=wifi,
        speakers=speakers,
        device_name=device_name,
        nfc_tags=nfc_tags,
        pause_on_remove=flags.get("pause_on_remove", False),
        wifi_tags=flags.get("wifi_tags", True),
        auto_update=auto_update,
        github_repo=github_repo,
        update_token=update_token,
        warnings=tuple(warnings),
    )


class _Skip(Exception):
    """An invalid entry: it is skipped and the message becomes a warning."""


def _check(problem: str | None) -> None:
    if problem:
        raise _Skip(problem)


def _section(parent: Mapping[str, Any], key: str, kind: type, problems: list[str], prefix: str = "") -> Any:
    """parent[key] if it has the expected kind (list or Mapping); empty if missing; otherwise a problem."""
    empty: Any = [] if kind is list else {}
    value = parent.get(key, empty)
    if isinstance(value, kind):
        return value
    problems.append(f"{prefix}{key} must be {'a list' if kind is list else 'an object'}")
    return empty


def _given(section: Mapping[str, Any], key: str) -> Any:
    """section[key], or None when it is missing, null or empty."""
    value = section.get(key)
    return None if value is None or value == "" else value


def _flag(
    section: Mapping[str, Any], key: str, label: str, problems: list[str], default: bool = False
) -> bool:
    value = section.get(key, default)
    if isinstance(value, bool):
        return value
    problems.append(f"{label}.{key} must be true or false")
    return default


def _whole_number(section: Mapping[str, Any], key: str, label: str, problems: list[str], default: int) -> int:
    # A quoted number is an error, not a skipped entry, so the import keeps the last good copy.
    value = section.get(key, default)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    problems.append(f"{label}.{key} must be a whole number")
    return default


def _wifi_seeds(entries: list[Any], problems: list[str], warnings: list[str]) -> tuple[WifiSeed, ...]:
    seeds = []
    for index, entry in enumerate(entries):
        label = _wifi_label(index, entry)
        try:
            seeds.append(_wifi_seed(entry, label, problems))
        except _Skip as skip:
            warnings.append(f"{label} skipped: {skip}")
    return tuple(seeds)


def _wifi_label(index: int, entry: Any) -> str:
    """wifi[<SSID>] for messages, or wifi[<index>] when the SSID is unusable."""
    ssid = entry.get("ssid") if isinstance(entry, Mapping) else None
    return f"wifi[{ssid}]" if ssid_error(ssid) is None else f"wifi[{index}]"


def _wifi_seed(entry: Any, label: str, problems: list[str]) -> WifiSeed:
    if not isinstance(entry, Mapping):
        raise _Skip("not an object")
    priority = _whole_number(entry, "priority", label, problems, default=5)
    hidden = _flag(entry, "hidden", label, problems)
    _check(ssid_error(entry.get("ssid")))
    secret, security = _wifi_secret(entry)
    if not -999 <= priority <= 999:
        raise _Skip("priority must be -999..999")
    return WifiSeed(entry["ssid"], priority, secret, security, hidden)


def _wifi_secret(entry: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """(secret, security). psk_hash wins over psk; without a secret only "open" keeps its security."""
    psk_hash = _given(entry, "psk_hash")
    if psk_hash is not None and not is_psk_hash(psk_hash):
        raise _Skip("psk_hash must be 64 hex digits")
    secret = psk_hash if psk_hash is not None else _given(entry, "psk")
    security = _given(entry, "security")
    if security is None:
        security = "wpa-psk" if secret is not None else None
    elif security not in SECURITIES:
        raise _Skip("security must be wpa-psk, sae or open")
    if psk_hash is not None and security != "wpa-psk":
        raise _Skip("psk_hash only works with wpa-psk")
    if secret is None:
        # Priority only, e.g. an entry whose secret was scrubbed after the import.
        return None, ("open" if security == "open" else None)
    _check(passphrase_error(secret, security))
    return secret, security


def _speakers(bluetooth: Mapping[str, Any], problems: list[str], warnings: list[str]) -> tuple[Speaker, ...]:
    """Speakers by priority, highest first (stable); a legacy speaker_mac gets priority 10."""
    if "speakers" in bluetooth:
        found = _section(bluetooth, "speakers", list, problems, prefix="bluetooth.")
        entries = [(f"bluetooth.speakers[{index}]", entry) for index, entry in enumerate(found)]
    elif "speaker_mac" in bluetooth:
        entries = [("bluetooth.speaker_mac", _legacy_speaker_entry(bluetooth))]
    else:
        entries = []
    speakers = []
    for label, entry in entries:
        try:
            speakers.append(_speaker(entry, label, problems))
        except _Skip as skip:
            warnings.append(f"{label} skipped: {skip}")
    return tuple(sorted(speakers, key=lambda speaker: speaker.priority, reverse=True))


def _speaker(entry: Any, label: str, problems: list[str]) -> Speaker:
    if not isinstance(entry, Mapping):
        raise _Skip("not an object")
    priority = _whole_number(entry, "priority", label, problems, default=0)
    try:
        mac = normalize_mac(entry.get("mac"))
    except ValueError as exc:
        raise _Skip(str(exc)) from None
    if mac in PLACEHOLDER_MACS:
        raise _Skip(f"placeholder MAC {mac}")
    if not 0 <= priority <= 10:
        raise _Skip("priority must be 0..10")
    name = _given(entry, "name")
    if name is None:
        name = mac
    _check(speaker_name_error(name))
    return Speaker(mac, name, priority)


def _legacy_speaker_entry(bluetooth: Mapping[str, Any]) -> dict[str, Any]:
    """Legacy speaker_mac/speaker_name as a speakers entry: priority 10, the name defaults to the MAC."""
    mac = bluetooth.get("speaker_mac")
    with contextlib.suppress(ValueError):
        mac = normalize_mac(mac)  # an invalid MAC stays as written; parse_config reports it
    name = _given(bluetooth, "speaker_name")
    return {"mac": mac, "name": mac if name is None else name, "priority": 10}


def _spotify(spotify: Mapping[str, Any], problems: list[str], warnings: list[str]) -> str:
    """The receiver name; Web API keys of the old Spotify client are only reported."""
    name = spotify.get("device_name", DEFAULT_DEVICE_NAME)
    error = device_name_error(name)
    if error:
        problems.append(f"spotify.device_name: {error}")
    ignored = [f"spotify.{key}" for key in _WEB_API_KEYS if key in spotify]
    if ignored:
        warnings.append(f"{', '.join(ignored)} ignored: the receiver needs no Spotify Web API keys")
    return name


def _github_repo(update: Mapping[str, Any], warnings: list[str]) -> str:
    repo = _given(update, "github_repo")
    if repo is None:
        return ""
    try:
        return normalize_repo(repo)
    except ValueError:
        # Never echo the value: a pasted URL may contain a token.
        warnings.append("update.github_repo ignored: expected owner/name or a GitHub URL")
        return ""


def _update_token(update: Mapping[str, Any], warnings: list[str]) -> str | None:
    token = _given(update, "token")
    if token is None:
        return None
    if isinstance(token, str) and _GITHUB_TOKEN.fullmatch(token.strip()):
        return token.strip()
    warnings.append("update.token ignored: not a valid GitHub token")
    return None


def _nfc_tags(tags: Mapping[str, Any], warnings: list[str]) -> Mapping[str, str]:
    """Normalized tag UID → value; the value itself is checked when the tag is played."""
    result: dict[str, str] = {}
    for uid, value in tags.items():
        try:
            key = normalize_uid(uid)
        except ValueError as exc:
            warnings.append(f"nfc_tags[{uid!r}] skipped: {exc}")
            continue
        if not isinstance(value, str):
            warnings.append(f"nfc_tags[{key}] skipped: value must be text")
            continue
        if key in result:
            warnings.append(f"nfc_tags[{key}] defined twice; the last entry wins")
        result[key] = value
    return MappingProxyType(result)


# --- Writing ---


def write_text_atomic(
    path: Path, text: str, *, mode: int = 0o644, owner: tuple[int, int] | None = None
) -> None:
    """Replace `path` atomically: temp file, fsync, rename, fsync of the directory.

    A failure before the rename removes the temp file and leaves the old file intact. Mode and
    owner are set on the temp file, so the final name never carries the wrong permissions.
    """
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
            file.write(text)
            file.flush()
            os.fchmod(file.fileno(), mode)
            if owner is not None:
                os.fchown(file.fileno(), *owner)
            os.fsync(file.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)


def write_json_atomic(
    path: Path, data: Any, *, mode: int = 0o644, owner: tuple[int, int] | None = None
) -> None:
    """write_text_atomic with indented UTF-8 JSON and a trailing newline."""
    write_text_atomic(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n", mode=mode, owner=owner)


def _fsync_dir(directory: Path) -> None:
    """Persist the rename itself."""
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


# --- Device copy and secrets ---


def to_device_dict(cfg: Config) -> dict[str, Any]:
    """The canonical config shape for the device copy: no secrets, no token, no Web API keys."""
    return {
        "wifi": [_seed_dict(seed) for seed in cfg.wifi],
        "bluetooth": {
            "speakers": [{"mac": s.mac, "name": s.name, "priority": s.priority} for s in cfg.speakers]
        },
        "spotify": {"device_name": cfg.device_name},
        "nfc_tags": dict(cfg.nfc_tags),
        "behavior": {"pause_on_remove": cfg.pause_on_remove, "wifi_tags": cfg.wifi_tags},
        "update": {"auto_update": cfg.auto_update, "github_repo": cfg.github_repo},
    }


def _seed_dict(seed: WifiSeed) -> dict[str, Any]:
    entry: dict[str, Any] = {"ssid": seed.ssid, "priority": seed.priority, "hidden": seed.hidden}
    if seed.security == "open":  # without its secret, any other seed only carries the priority
        entry["security"] = "open"
    return entry


def scrub_secrets(
    raw: Mapping[str, Any], *, imported_wifi: Collection[str] = (), token_saved: bool = False
) -> tuple[dict[str, Any], list[str]]:
    """Remove only the secrets that are stored safely elsewhere now; all other keys stay untouched.

    WiFi secrets go for entries whose SSID is in `imported_wifi`, update.token only if `token_saved`;
    the unused spotify.client_secret always goes. Returns (new raw dict, removed keys such as
    "wifi[Home].psk").
    """
    result = _copy(raw)
    removed: list[str] = []
    entries = result.get("wifi")
    for index, entry in enumerate(entries if isinstance(entries, list) else []):
        ssid = entry.get("ssid") if isinstance(entry, dict) else None
        if not (isinstance(ssid, str) and ssid in imported_wifi):
            continue  # skipped, failed or without a usable SSID: the secret stays
        for key in ("psk", "psk_hash"):
            if key in entry:
                del entry[key]
                removed.append(f"{_wifi_label(index, entry)}.{key}")
    for section, key, remove in (("update", "token", token_saved), ("spotify", "client_secret", True)):
        part = result.get(section)
        if remove and isinstance(part, dict) and key in part:
            del part[key]
            removed.append(f"{section}.{key}")
    return result, removed


# --- Raw edits for the CLIs ---


def upsert_speaker(raw: Mapping[str, Any], speaker: Speaker) -> dict[str, Any]:
    """Add `speaker` to bluetooth.speakers or update the entry with its MAC; a legacy speaker is migrated."""
    mac = normalize_mac(speaker.mac)
    result = _copy(raw)
    bluetooth = result.setdefault("bluetooth", {})
    if not isinstance(bluetooth, dict):
        raise ConfigError(["bluetooth must be an object"])
    _migrate_legacy_speaker(bluetooth)
    speakers = bluetooth.setdefault("speakers", [])
    if not isinstance(speakers, list):
        raise ConfigError(["bluetooth.speakers must be a list"])
    entry = {"mac": mac, "name": speaker.name, "priority": speaker.priority}
    for index, old in enumerate(speakers):
        if _is_speaker(old, mac):
            speakers[index] = {**old, **entry}
            break
    else:
        speakers.append(entry)
    return result


def remove_speaker(raw: Mapping[str, Any], mac: str) -> tuple[dict[str, Any], bool]:
    """Remove the speaker with `mac`, also a legacy single speaker. Returns (new raw dict, removed)."""
    mac = normalize_mac(mac)
    result = _copy(raw)
    bluetooth = result.get("bluetooth")
    if not isinstance(bluetooth, dict):
        return result, False
    if "speakers" not in bluetooth:
        if not _same_mac(bluetooth.get("speaker_mac"), mac):
            return result, False
        bluetooth.pop("speaker_mac")
        bluetooth.pop("speaker_name", None)
        return result, True
    speakers = bluetooth["speakers"]
    if not isinstance(speakers, list):
        return result, False
    kept = [entry for entry in speakers if not _is_speaker(entry, mac)]
    bluetooth["speakers"] = kept
    return result, len(kept) < len(speakers)


def remove_wifi_seed(raw: Mapping[str, Any], ssid: str) -> tuple[dict[str, Any], bool]:
    """Remove every wifi entry with exactly this SSID. Returns (new raw dict, removed)."""
    result = _copy(raw)
    entries = result.get("wifi")
    if not isinstance(entries, list):
        return result, False
    kept = [entry for entry in entries if not (isinstance(entry, dict) and entry.get("ssid") == ssid)]
    result["wifi"] = kept
    return result, len(kept) < len(entries)


def _copy(raw: Mapping[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(dict(raw))


def _migrate_legacy_speaker(bluetooth: dict[str, Any]) -> None:
    """Replace bluetooth.speaker_mac/speaker_name with one speakers entry."""
    if "speakers" in bluetooth or "speaker_mac" not in bluetooth:
        return
    bluetooth["speakers"] = [_legacy_speaker_entry(bluetooth)]
    del bluetooth["speaker_mac"]
    bluetooth.pop("speaker_name", None)


def _same_mac(value: Any, mac: str) -> bool:
    return isinstance(value, str) and value.upper() == mac


def _is_speaker(entry: Any, mac: str) -> bool:
    return isinstance(entry, dict) and _same_mac(entry.get("mac"), mac)
