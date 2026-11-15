"""nfc-bt: scan for speakers, pair and save them, list and remove them.

Runs as root through the nfc-bt wrapper. Saving writes the master config (BOOT_CONFIG) and
re-imports it. Exit codes: 0 ok, 1 error, 2 usage.
"""

import argparse
import sys
from collections.abc import Callable
from typing import Any

from nfc_player.bluetooth.bluez import Bluez, is_random_ble_name, printable
from nfc_player.core import paths
from nfc_player.core.config import (
    ConfigError,
    Speaker,
    parse_config,
    read_raw,
    remove_speaker,
    upsert_speaker,
    write_json_atomic,
)
from nfc_player.core.process import run
from nfc_player.core.validate import PLACEHOLDER_MACS, normalize_mac, speaker_name_error

_IMPORT_UNIT = "nfc-player-config.service"
_NAME_LIMIT = 64  # speaker_name_error allows 1..64 characters


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # --help, or a usage error argparse has printed
        return exc.code if isinstance(exc.code, int) else 2
    try:
        return args.handler(args, Bluez(run))
    except (OSError, ConfigError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Aborted.", file=sys.stderr)
        return 130


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nfc-bt", description="Bluetooth speakers of the NFC player.")
    commands = parser.add_subparsers(dest="command", required=True)

    scan = commands.add_parser("scan", help="scan for nearby speakers")
    scan.add_argument("--duration", type=_whole_number(1, 300), default=10, help="seconds (default 10)")
    scan.set_defaults(handler=_scan)

    connect = commands.add_parser("connect", help="pair a speaker and save it")
    connect.add_argument("speaker", type=_speaker_id, help="MAC address or part of the name")
    connect.add_argument(
        "--priority",
        type=_whole_number(1, 10),
        default=5,
        help="1..10, the highest is tried first (default 5)",
    )
    connect.set_defaults(handler=_connect)

    listing = commands.add_parser("list", help="show the saved speakers")
    listing.set_defaults(handler=_list)

    remove = commands.add_parser("remove", help="remove a saved speaker")
    remove.add_argument("mac", type=_mac, help="MAC address")
    remove.add_argument("--unpair", action="store_true", help="also make Bluetooth forget the speaker")
    remove.set_defaults(handler=_remove)
    return parser


# --- Argument types (a failure exits with 2) ---


def _whole_number(low: int, high: int) -> Callable[[str], int]:
    def parse(text: str) -> int:
        try:
            value = int(text)
        except ValueError:
            value = low - 1
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f"must be a whole number from {low} to {high}")
        return value

    return parse


def _mac(text: str) -> str:
    try:
        return normalize_mac(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _speaker_id(text: str) -> str:
    """A MAC (normalized, not a placeholder) or a non-empty part of a device name."""
    try:
        mac = normalize_mac(text)
    except ValueError:
        if not text.strip():
            raise argparse.ArgumentTypeError("give a MAC address or a device name") from None
        return text.strip()
    if mac in PLACEHOLDER_MACS:
        raise argparse.ArgumentTypeError(f"{mac} is a placeholder, not a speaker")
    return mac


# --- Commands ---


def _scan(args: argparse.Namespace, bluez: Bluez) -> int:
    _power_on(bluez)
    print(f"Scanning for {args.duration} s, put the speaker into pairing mode ...")
    devices = bluez.scan(args.duration)
    if not devices:
        print("No named devices found.")
        print("Tip: switch the speaker off and on, then enable its pairing mode.")
        print("Tip: scan longer with: nfc-bt scan --duration 30")
        return 0
    print(f"Found {len(devices)} device(s):\n")
    print(f"  {'#':<4} {'MAC address':<18} Name")
    for number, (mac, name) in enumerate(devices, 1):
        print(f"  {number:<4} {mac:<18} {name}")
    print("\nSave one with: nfc-bt connect <MAC> --priority 10")
    return 0


def _connect(args: argparse.Namespace, bluez: Bluez) -> int:
    _power_on(bluez)
    found = _resolve(bluez, args.speaker)
    if found is None:
        print(f"No known device matches {args.speaker!r}. Run 'nfc-bt scan' first.", file=sys.stderr)
        return 1
    mac, name = found
    print(f"Pairing {_label(name, mac)}, this takes about 25 s ...")
    info = bluez.pair_trust_connect(mac)
    if info.name and not is_random_ble_name(info.name, mac):
        name = info.name
    print(f"Status: paired={info.paired}, trusted={info.trusted}, connected={info.connected}")
    if not info.paired:
        print(
            f"Pairing failed: put {_label(name, mac)} into pairing mode (blinking LED) and try again. "
            "Nothing saved.",
            file=sys.stderr,
        )
        return 1
    if info.connected:
        print(f"Connected to {name}.")
    else:
        print(f"Paired with {name}, not connected (switched off?).")
    speaker = Speaker(mac, _config_name(name, mac), args.priority)
    raw = upsert_speaker(_read_boot_config(), speaker)
    return 0 if _save(raw, f"Saved {_label(speaker.name, mac)} with priority {speaker.priority}") else 1


def _list(args: argparse.Namespace, bluez: Bluez) -> int:
    raw = _read_boot_config()
    # Only the bluetooth section: an error elsewhere in the file must not hide the speakers.
    config = parse_config({"bluetooth": raw["bluetooth"]} if "bluetooth" in raw else {})
    for warning in config.warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    if not config.speakers:
        print("No speakers configured. Add one with: nfc-bt connect <MAC> --priority 10")
        return 0
    print(f"Configured speakers ({paths.BOOT_CONFIG}):\n")
    print(f"  {'Priority':<9} {'MAC address':<18} Name")
    for speaker in config.speakers:
        print(f"  {speaker.priority:<9} {speaker.mac:<18} {speaker.name}")
    return 0


def _remove(args: argparse.Namespace, bluez: Bluez) -> int:
    raw, removed = remove_speaker(_read_boot_config(), args.mac)
    imported = True
    if removed:
        imported = _save(raw, f"Removed {args.mac}")
    else:
        print(f"{args.mac} is not in {paths.BOOT_CONFIG}.")
    unpaired = False
    if args.unpair:
        unpaired = bluez.remove(args.mac)
        print(f"Bluetooth forgot {args.mac}." if unpaired else f"Bluetooth does not know {args.mac}.")
    if not (removed or unpaired):
        return 1
    return 0 if imported else 1


# --- Helpers ---


def _power_on(bluez: Bluez) -> None:
    if not bluez.power_on():
        print("Warning: the Bluetooth adapter could not be powered on.", file=sys.stderr)


def _resolve(bluez: Bluez, speaker: str) -> tuple[str, str] | None:
    """(MAC, name) for a MAC, or for the first known device whose name contains `speaker`."""
    try:
        mac = normalize_mac(speaker)
    except ValueError:
        needle = speaker.lower()
        return next(((mac, name) for mac, name in bluez.devices() if needle in name.lower()), None)
    info = bluez.info(mac)
    if info is not None and info.name:
        return mac, info.name
    for known, name in bluez.devices():
        if known == mac and name and not is_random_ble_name(name, mac):
            return mac, name
    return mac, mac


def _label(name: str, mac: str) -> str:
    return mac if name == mac else f"{name} ({mac})"


def _config_name(name: str, mac: str) -> str:
    """`name` printable and cut to 64 characters, so the config loader accepts it; else the MAC."""
    short = printable(name)[:_NAME_LIMIT].strip()
    return short if speaker_name_error(short) is None else mac


def _read_boot_config() -> dict[str, Any]:
    """The master config as a raw dict; empty if it does not exist yet."""
    try:
        return read_raw(paths.BOOT_CONFIG)
    except FileNotFoundError:
        return {}


def _save(raw: dict[str, Any], done: str) -> bool:
    """Write the master config and re-import it; False if the import failed."""
    write_json_atomic(paths.BOOT_CONFIG, raw)  # no owner=: /boot/firmware is vfat
    print(f"{done} in {paths.BOOT_CONFIG}.")
    if run(["systemctl", "start", _IMPORT_UNIT]).ok:
        return True
    print(f"Config import failed, see: journalctl -u {_IMPORT_UNIT}", file=sys.stderr)
    return False


if __name__ == "__main__":
    raise SystemExit(main())
