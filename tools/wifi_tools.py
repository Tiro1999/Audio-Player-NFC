#!/usr/bin/env python3
# --- Auto-activate project venv if available ---
import os, sys
_venv_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "venv", "bin", "python3")
if os.path.exists(_venv_py) and os.path.abspath(sys.executable) != os.path.abspath(_venv_py):
    os.execv(_venv_py, [_venv_py] + sys.argv)
# -----------------------------------------------
"""WiFi management tools – add networks with hashed passwords.

Passwords are converted to a WPA2 PSK hash (PBKDF2-SHA1, same as
wpa_passphrase).  The plaintext password is NEVER stored.

Usage (on the Pi via SSH):

    python3 ~/nfc-player/tools/wifi_tools.py add "MySSID" "MyPassword" --priority 10
    python3 ~/nfc-player/tools/wifi_tools.py list
    python3 ~/nfc-player/tools/wifi_tools.py remove "MySSID"
    python3 ~/nfc-player/tools/wifi_tools.py apply
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys

CONFIG_PATHS = ["/boot/firmware/config.json", "/boot/config.json"]


def wpa_psk(ssid, password):
    """Derive the WPA2 PSK (identical to wpa_passphrase output)."""
    return hashlib.pbkdf2_hmac(
        "sha1", password.encode("utf-8"), ssid.encode("utf-8"), 4096, 32
    ).hex()


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
    """Save config.json – uses sudo if direct write fails (boot partition)."""
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except PermissionError:
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
            json.dump(data, tmp, indent=2, ensure_ascii=False)
            tmp_path = tmp.name
        subprocess.run(["sudo", "cp", tmp_path, path], check=True)
        os.unlink(tmp_path)
    print(f"💾  Saved to {path}")


# ── ADD ────────────────────────────────────────────────────────────────────

def cmd_add(args):
    """Hash the password and store the network in config.json."""
    ssid = args.ssid
    password = args.password
    priority = args.priority

    psk_hash = wpa_psk(ssid, password)

    config, config_path = _load_config()
    if "wifi" not in config:
        config["wifi"] = []

    existing = next((w for w in config["wifi"] if w["ssid"] == ssid), None)
    if existing:
        existing["psk_hash"] = psk_hash
        existing.pop("psk", None)          # remove plaintext if present
        existing["priority"] = priority
        print(f"📝  Updated WiFi network '{ssid}'")
    else:
        config["wifi"].append({"ssid": ssid, "psk_hash": psk_hash, "priority": priority})
        print(f"➕  Added WiFi network '{ssid}'")

    config["wifi"].sort(key=lambda w: w.get("priority", 0), reverse=True)
    _save_config(config, config_path)

    print(f"    Priority : {priority}")
    print(f"    PSK hash : {psk_hash[:16]}…  (password NOT stored)")


# ── LIST ───────────────────────────────────────────────────────────────────

def cmd_list(args):
    """Show configured WiFi networks (no passwords shown)."""
    config, config_path = _load_config()
    networks = config.get("wifi", [])

    if not networks:
        print("No WiFi networks configured.")
        print("Add one:  python3 tools/wifi_tools.py add \"SSID\" \"Password\"")
        return

    print(f"Configured WiFi networks ({config_path}):\n")
    print(f"  {'Prio':<6} {'SSID':<30} {'Security'}")
    print(f"  {'─' * 6} {'─' * 30} {'─' * 20}")
    for w in networks:
        if "psk_hash" in w:
            sec = "🔒 hashed"
        elif "psk" in w:
            sec = "⚠️  plaintext!"
        else:
            sec = "open"
        print(f"  {w.get('priority', 0):<6} {w['ssid']:<30} {sec}")


# ── REMOVE ─────────────────────────────────────────────────────────────────

def cmd_remove(args):
    config, config_path = _load_config()
    networks = config.get("wifi", [])
    before = len(networks)
    config["wifi"] = [w for w in networks if w["ssid"] != args.ssid]
    if len(config["wifi"]) == before:
        print(f"❌  '{args.ssid}' not found in config.")
        return
    _save_config(config, config_path)
    print(f"🗑️   Removed '{args.ssid}'")


# ── APPLY ──────────────────────────────────────────────────────────────────

def cmd_apply(args):
    """Push WiFi networks from config.json into NetworkManager."""
    config, _ = _load_config()
    networks = config.get("wifi", [])
    if not networks:
        print("No WiFi networks to apply.")
        return

    for w in networks:
        ssid = w["ssid"]
        # psk_hash (64 hex chars) is accepted by nmcli as a raw PSK
        psk = w.get("psk_hash") or w.get("psk", "")
        priority = w.get("priority", 0)

        print(f"📡  Configuring '{ssid}' (priority {priority}) …")

        check = subprocess.run(
            ["nmcli", "connection", "show", ssid], capture_output=True
        )
        if check.returncode == 0:
            subprocess.run([
                "sudo", "nmcli", "connection", "modify", ssid,
                "wifi-sec.psk", psk,
                "connection.autoconnect-priority", str(priority),
            ], capture_output=True)
            print(f"    ✔ Updated")
        else:
            subprocess.run([
                "sudo", "nmcli", "connection", "add",
                "type", "wifi", "con-name", ssid, "ssid", ssid,
                "wifi-sec.key-mgmt", "wpa-psk",
                "wifi-sec.psk", psk,
                "connection.autoconnect", "yes",
                "connection.autoconnect-priority", str(priority),
            ], capture_output=True)
            print(f"    ✔ Added")

    print(f"\n✅  {len(networks)} network(s) configured in NetworkManager")


# ── SCAN ───────────────────────────────────────────────────────────────────

def cmd_scan(args):
    """Scan for available WiFi networks."""
    print("📡  Scanning for WiFi networks …\n")
    result = subprocess.run(
        ["nmcli", "-t", "-f", "SIGNAL,SECURITY,SSID", "dev", "wifi", "list", "--rescan", "yes"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"❌  nmcli error: {result.stderr.strip()}")
        return

    lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    if not lines:
        print("No WiFi networks found.")
        return

    print(f"  {'Signal':<8} {'Security':<20} {'SSID'}")
    print(f"  {'─' * 8} {'─' * 20} {'─' * 30}")
    seen = set()
    for line in sorted(lines, key=lambda l: int(l.split(":")[0] or "0"), reverse=True):
        parts = line.split(":", 2)
        if len(parts) < 3 or not parts[2]:
            continue
        ssid = parts[2]
        if ssid in seen:
            continue
        seen.add(ssid)
        signal = parts[0] + "%"
        security = parts[1] if parts[1] else "Open"
        print(f"  {signal:<8} {security:<20} {ssid}")

    print(f"\n  {len(seen)} network(s) found")


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="WiFi tools for NFC Spotify Player")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="Scan for available WiFi networks")
    p_scan.set_defaults(func=cmd_scan)

    p_add = sub.add_parser("add", help="Add WiFi network (password is hashed, never stored)")
    p_add.add_argument("ssid", help="WiFi SSID")
    p_add.add_argument("password", help="WiFi password (will be hashed)")
    p_add.add_argument("--priority", type=int, default=5, help="Priority 1-10 (10 = highest)")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="List configured WiFi networks")
    p_list.set_defaults(func=cmd_list)

    p_rm = sub.add_parser("remove", help="Remove a WiFi network")
    p_rm.add_argument("ssid", help="SSID to remove")
    p_rm.set_defaults(func=cmd_remove)

    p_apply = sub.add_parser("apply", help="Apply config to NetworkManager")
    p_apply.set_defaults(func=cmd_apply)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
