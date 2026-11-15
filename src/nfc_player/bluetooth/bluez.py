"""bluetoothctl wrapper: device state, trust, connect, remove, and the interactive scan and pair session.

Device names come from the radio and are untrusted: non-printable characters (terminal escapes,
control and bidi characters) are removed when the bluetoothctl output is parsed.
"""

import logging
import re
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from nfc_player.core.process import Result, Runner, run
from nfc_player.core.validate import normalize_mac

log = logging.getLogger(__name__)

_DEVICE_LINE = re.compile(r"Device ((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})(?: (.*))?")
_BREDR_SCAN = ("menu scan", "transport bredr", "back", "scan on")  # classic devices only, like speakers


@dataclass(frozen=True)
class DeviceInfo:
    mac: str
    name: str | None  # None if the device never sent a name
    paired: bool
    trusted: bool
    connected: bool


def is_random_ble_name(name: str, mac: str) -> bool:
    """True if BlueZ shows the address as the name: an unnamed, usually random BLE device."""
    mac = mac.upper()
    return name.strip().upper() in (mac, mac.replace(":", "-"))


def printable(text: str) -> str:
    """`text` without non-printable characters: no terminal escapes, control or bidi characters."""
    return "".join(char for char in text if char.isprintable()).strip()


def _lines(output: str) -> list[str]:
    # Not splitlines(): it also splits at characters a device name may contain, such as U+2028.
    return [line.strip() for line in output.split("\n")]


class BluetoothctlSession:
    """Interactive bluetoothctl for scanning and pairing.

    A scan filter lasts only as long as the bluetoothctl process, so scan and pair run in one
    session. It needs a live stdin, which is why it does not use core.process.run.
    """

    def __init__(self, argv: Sequence[str] = ("bluetoothctl",)) -> None:
        self._process = subprocess.Popen(
            list(argv),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
        )

    def send(self, *commands: str) -> None:
        self._process.stdin.write("".join(f"{command}\n" for command in commands))
        self._process.stdin.flush()

    def wait(self, seconds: float) -> None:
        time.sleep(seconds)

    def close(self) -> None:
        """Send exit and wait; kill bluetoothctl if it has not ended after 5 s."""
        try:
            self._process.communicate("exit\n", timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.communicate()


class Bluez:
    """bluetoothctl commands. MACs are expected in the normalized form AA:BB:CC:DD:EE:FF."""

    def __init__(self, runner: Runner = run, *, session_factory: Callable[[], Any] | None = None) -> None:
        self._runner = runner
        self._session_factory = session_factory or BluetoothctlSession

    def power_on(self) -> bool:
        return self._ctl("power", "on").ok

    def info(self, mac: str) -> DeviceInfo | None:
        """State of a device BlueZ knows; None for an unknown device."""
        result = self._ctl("info", mac)
        fields = {}
        for line in _lines(result.stdout):
            key, colon, value = line.partition(":")
            if colon:
                fields[key] = value.strip()
        if not result.ok or "Paired" not in fields:
            return None
        return DeviceInfo(
            mac=mac.upper(),
            name=printable(fields.get("Name", "")) or None,
            paired=fields["Paired"] == "yes",
            trusted=fields.get("Trusted") == "yes",
            connected=fields.get("Connected") == "yes",
        )

    def trust(self, mac: str) -> bool:
        return self._ctl("trust", mac).ok

    def connect(self, mac: str) -> bool:
        return self._ctl("connect", mac, timeout=15).ok

    def devices(self) -> list[tuple[str, str]]:
        """(MAC, name) of every device BlueZ knows, from its "Device <MAC> <name>" lines."""
        found = []
        for line in _lines(self._ctl("devices").stdout):
            match = _DEVICE_LINE.fullmatch(line)
            if match:
                found.append((match[1].upper(), printable(match[2] or "")))
        return found

    def remove(self, mac: str) -> bool:
        return self._ctl("remove", mac).ok

    def scan(self, seconds: int) -> list[tuple[str, str]]:
        """Scan for classic devices for `seconds`; returns the named devices BlueZ knows afterwards.

        Before the scan, devices that are neither paired nor trusted are removed, so stale entries
        vanish; paired and trusted speakers stay.
        """
        for mac, _name in self.devices():
            info = self.info(mac)
            if info is not None and not info.paired and not info.trusted:
                self.remove(mac)
        session = self._session_factory()
        try:
            session.send(*_BREDR_SCAN)
            session.wait(seconds)
            session.send("scan off")
        finally:
            session.close()
        return [(mac, name) for mac, name in self.devices() if name and not is_random_ble_name(name, mac)]

    def pair_trust_connect(self, mac: str) -> DeviceInfo:
        """Find, pair, trust and connect a speaker in one session, then return its state."""
        mac = normalize_mac(mac)  # it becomes part of session lines, not of an argv
        steps = (
            (_BREDR_SCAN, 8),  # BlueZ must have seen the speaker before it can pair
            (("scan off", f"pair {mac}"), 8),
            ((f"trust {mac}",), 1),
            ((f"connect {mac}",), 5),
        )
        session = self._session_factory()
        try:
            for commands, seconds in steps:
                session.send(*commands)
                session.wait(seconds)
        finally:
            session.close()
        return self.info(mac) or DeviceInfo(mac, None, paired=False, trusted=False, connected=False)

    def _ctl(self, *args: str, timeout: float = 15) -> Result:
        result = self._runner(["bluetoothctl", *args], timeout=timeout)
        if not result.ok:
            log.debug("bluetoothctl %s failed: %s", args[0], (result.stdout + result.stderr).strip())
        return result
