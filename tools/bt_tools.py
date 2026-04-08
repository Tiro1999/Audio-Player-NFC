#!/usr/bin/env python3
"""Bluetooth tools for the NFC Spotify Player.

Run on the Pi via SSH:

    python3 ~/nfc-player/tools/bt_tools.py scan
    python3 ~/nfc-player/tools/bt_tools.py connect AA:BB:CC:DD:EE:FF
    python3 ~/nfc-player/tools/bt_tools.py connect AA:BB:CC:DD:EE:FF --priority 10
    python3 ~/nfc-player/tools/bt_tools.py connect "JBL Flip 5" --priority 8
    python3 ~/nfc-player/tools/bt_tools.py list
    python3 ~/nfc-player/tools/bt_tools.py remove AA:BB:CC:DD:EE:FF
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

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
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"💾  Saved to {path}")


def _run(cmd, timeout=15):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ── SCAN ───────────────────────────────────────────────────────────────────

def cmd_scan(args):
    """Scan for nearby Bluetooth devices."""
    duration = args.duration

    # Ensure Bluetooth is unblocked and powered on
    subprocess.run(["sudo", "rfkill", "unblock", "bluetooth"], capture_output=True)
    time.sleep(0.5)
    _run(["bluetoothctl", "power", "on"])
    time.sleep(1)

    print(f"🔍  Scanning for Bluetooth devices ({duration}s) …\n")

    proc = subprocess.Popen(
        ["bluetoothctl", "scan", "on"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(duration)
    finally:
        proc.terminate()
        proc.wait()

    result = _run(["bluetoothctl", "devices"])
    devices = []
    for line in result.stdout.strip().splitlines():
        m = re.match(r"Device\s+([0-9A-Fa-f:]{17})\s+(.*)", line)
        if m:
            devices.append({"mac": m.group(1), "name": m.group(2).strip()})

    if not devices:
        print("No devices found.")
        return

    print(f"Found {len(devices)} device(s):\n")
    print(f"  {'#':<4} {'MAC Address':<20} {'Name'}")
    print(f"  {'─' * 4} {'─' * 20} {'─' * 30}")
    for i, dev in enumerate(devices, 1):
        print(f"  {i:<4} {dev['mac']:<20} {dev['name']}")

    print(f"\nTo connect:  python3 tools/bt_tools.py connect <MAC> --priority 10")


# ── CONNECT ────────────────────────────────────────────────────────────────

def cmd_connect(args):
    """Pair, trust, connect a speaker and save it to config.json."""
    identifier = args.identifier
    priority = args.priority

    # Resolve MAC and name
    mac, name = _resolve_device(identifier)
    if not mac:
        print(f"❌  Device '{identifier}' not found. Run 'scan' first.")
        sys.exit(1)

    print(f"🔗  Connecting to {name} ({mac}) …")

    _run(["bluetoothctl", "pair", mac])
    time.sleep(1)
    _run(["bluetoothctl", "trust", mac])
    time.sleep(1)
    _run(["bluetoothctl", "connect", mac])
    time.sleep(3)

    # Verify
    info = _run(["bluetoothctl", "info", mac])
    connected = "Connected: yes" in info.stdout

    if connected:
        print(f"✅  Connected to {name}!")
    else:
        print(f"⚠️   Connection status unclear – device may need to be in pairing mode")

    # Save to config.json
    config, config_path = _load_config()

    if "bluetooth" not in config:
        config["bluetooth"] = {}

    bt = config["bluetooth"]

    # Migrate old single-speaker format if present
    if "speaker_mac" in bt and "speakers" not in bt:
        old = {
            "mac": bt.pop("speaker_mac"),
            "name": bt.pop("speaker_name", "Unknown"),
            "priority": 5,
        }
        bt["speakers"] = [old]

    if "speakers" not in bt:
        bt["speakers"] = []

    # Update or add
    existing = next((s for s in bt["speakers"] if s["mac"].upper() == mac.upper()), None)
    if existing:
        existing["name"] = name
        existing["priority"] = priority
        print(f"📝  Updated existing entry → priority {priority}")
    else:
        bt["speakers"].append({"mac": mac, "name": name, "priority": priority})
        print(f"➕  Added new speaker → priority {priority}")

    # Sort by priority (highest first)
    bt["speakers"].sort(key=lambda s: s.get("priority", 0), reverse=True)

    _save_config(config, config_path)

    print(f"\n📋  Current speakers:")
    _print_speakers(bt["speakers"])


def _resolve_device(identifier):
    """Resolve a MAC address or device name to (mac, name)."""
    if re.match(r"[0-9A-Fa-f:]{17}", identifier):
        mac = identifier.upper()
        info = _run(["bluetoothctl", "info", mac])
        m = re.search(r"Name:\s+(.+)", info.stdout)
        name = m.group(1).strip() if m else mac
        return mac, name

    # Search by name
    result = _run(["bluetoothctl", "devices"])
    for line in result.stdout.strip().splitlines():
        m = re.match(r"Device\s+([0-9A-Fa-f:]{17})\s+(.*)", line)
        if m and identifier.lower() in m.group(2).lower():
            return m.group(1), m.group(2).strip()

    return None, None


# ── LIST ───────────────────────────────────────────────────────────────────

def cmd_list(args):
    """List configured speakers from config.json."""
    config, config_path = _load_config()
    speakers = config.get("bluetooth", {}).get("speakers", [])

    if not speakers:
        print("No speakers configured.")
        print(f"Add one with:  python3 tools/bt_tools.py connect <MAC> --priority 10")
        return

    print(f"Configured speakers ({config_path}):\n")
    _print_speakers(speakers)


def _print_speakers(speakers):
    print(f"  {'Prio':<6} {'MAC Address':<20} {'Name'}")
    print(f"  {'─' * 6} {'─' * 20} {'─' * 30}")
    for s in speakers:
        prio = s.get("priority", 0)
        print(f"  {prio:<6} {s['mac']:<20} {s.get('name', '?')}")


# ── REMOVE ─────────────────────────────────────────────────────────────────

def cmd_remove(args):
    """Remove a speaker from config.json."""
    mac = args.mac.upper()
    config, config_path = _load_config()
    speakers = config.get("bluetooth", {}).get("speakers", [])

    before = len(speakers)
    config["bluetooth"]["speakers"] = [s for s in speakers if s["mac"].upper() != mac]
    after = len(config["bluetooth"]["speakers"])

    if before == after:
        print(f"❌  Speaker {mac} not found in config.")
        return

    _save_config(config, config_path)
    print(f"🗑️   Removed {mac} from config.")


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Bluetooth tools for NFC Spotify Player",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # scan
    p_scan = sub.add_parser("scan", help="Scan for nearby Bluetooth devices")
    p_scan.add_argument("--duration", type=int, default=10, help="Scan duration in seconds")
    p_scan.set_defaults(func=cmd_scan)

    # connect
    p_conn = sub.add_parser("connect", help="Connect a speaker and save to config")
    p_conn.add_argument("identifier", help="MAC address or device name")
    p_conn.add_argument("--priority", type=int, default=5, help="Priority 1-10 (10 = highest)")
    p_conn.set_defaults(func=cmd_connect)

    # list
    p_list = sub.add_parser("list", help="List configured speakers")
    p_list.set_defaults(func=cmd_list)

    # remove
    p_rm = sub.add_parser("remove", help="Remove a speaker from config")
    p_rm.add_argument("mac", help="MAC address to remove")
    p_rm.set_defaults(func=cmd_remove)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
