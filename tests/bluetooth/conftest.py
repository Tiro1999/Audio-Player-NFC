"""Fakes for the bluetooth tests: bluetoothctl and pactl on a simulated device table."""

import os
import subprocess
from dataclasses import dataclass

import pytest

from nfc_player.bluetooth.bluez import Bluez
from nfc_player.core.process import Result

ALSA_SINK = "alsa_output.platform-bcm2835_audio.stereo-fallback"
REAL_TOOLS = frozenset({"bluetoothctl", "pactl", "rfkill", "systemctl", "sudo"})


def refuse_real_tools(start):
    """Wrap subprocess.run or Popen so that starting one of REAL_TOOLS raises."""

    def guarded(args, *more, **kwargs):
        program = os.path.basename(str(args[0]))
        if program in REAL_TOOLS:
            raise AssertionError(f"a test started the real {program}")
        return start(args, *more, **kwargs)

    return guarded


@pytest.fixture(autouse=True)
def no_real_tools(monkeypatch):
    """A forgotten fake must fail the test: a real scan would remove devices from BlueZ."""
    monkeypatch.setattr(subprocess, "run", refuse_real_tools(subprocess.run))
    monkeypatch.setattr(subprocess, "Popen", refuse_real_tools(subprocess.Popen))


@dataclass
class FakeDevice:
    name: str | None = None
    paired: bool = False
    trusted: bool = False
    connected: bool = False
    pairable: bool = True  # in pairing mode
    reachable: bool = True  # switched on and in range


def _yes(flag: bool) -> str:
    return "yes" if flag else "no"


class FakeSession:
    """Interactive bluetoothctl: records commands and waits and applies the commands to the system."""

    def __init__(self, system: "FakeSystem") -> None:
        self.system = system
        self.sent: list[str] = []
        self.waits: list[float] = []
        self.closed = False

    def send(self, *commands: str) -> None:
        for command in commands:
            self.sent.append(command)
            self.system.session_command(command)

    def wait(self, seconds: float) -> None:
        self.waits.append(seconds)

    def close(self) -> None:
        self.closed = True


class FakeSystem:
    """Runner fake: bluetoothctl and pactl act on a device table, other commands succeed.

    Every argv lands in `calls`; `overrides` maps an argv tuple to a fixed Result.
    """

    def __init__(self) -> None:
        self.devices: dict[str, FakeDevice] = {}  # known to BlueZ
        self.nearby: dict[str, FakeDevice] = {}  # found by the next scan
        self.sinks = [ALSA_SINK]
        self.default_sink = ALSA_SINK
        self.overrides: dict[tuple[str, ...], Result] = {}
        self.calls: list[tuple[str, ...]] = []
        self.sessions: list[FakeSession] = []

    def add(self, mac: str, name: str | None = None, **flags: bool) -> FakeDevice:
        self.devices[mac] = FakeDevice(name, **flags)
        return self.devices[mac]

    def add_nearby(self, mac: str, name: str | None = None, **flags: bool) -> None:
        self.nearby[mac] = FakeDevice(name, **flags)

    def open_session(self) -> FakeSession:
        self.sessions.append(FakeSession(self))
        return self.sessions[-1]

    def calls_of(self, *prefix: str) -> list[tuple[str, ...]]:
        return [call for call in self.calls if call[: len(prefix)] == prefix]

    def __call__(self, args, *, timeout: float = 15.0, input=None, env=None) -> Result:
        argv = tuple(args)
        self.calls.append(argv)
        if argv in self.overrides:
            return self.overrides[argv]
        if argv[0] == "bluetoothctl":
            return self._bluetoothctl(*argv[1:])
        if argv[0] == "pactl":
            return self._pactl(*argv[1:])
        return Result(0, "", "")

    def session_command(self, command: str) -> None:
        verb, _, mac = command.partition(" ")
        device = self.devices.get(mac)
        if command == "scan on":
            for found, nearby in self.nearby.items():
                self.devices.setdefault(found, nearby)
        elif verb == "pair" and device and device.pairable and device.reachable:
            device.paired = True
        elif verb == "trust" and device:
            device.trusted = True
        elif verb == "connect" and device and device.paired and device.reachable:
            device.connected = True

    def _bluetoothctl(self, command: str, *rest: str) -> Result:
        if command == "power":
            return Result(0, "Changing power on succeeded\n", "")
        if command == "devices":
            return Result(0, "".join(f"Device {mac} {self._alias(mac)}\n" for mac in self.devices), "")
        mac = rest[0]
        device = self.devices.get(mac)
        if device is None:
            return Result(1, f"Device {mac} not available\n", "")
        if command == "info":
            return Result(0, self._info(mac, device), "")
        if command == "trust":
            device.trusted = True
            return Result(0, f"Changing {mac} trust succeeded\n", "")
        if command == "remove":
            del self.devices[mac]
            return Result(0, "Device has been removed\n", "")
        if command == "connect":
            if device.paired and device.reachable:
                device.connected = True
                return Result(0, f"Attempting to connect to {mac}\nConnection successful\n", "")
            failure = "Failed to connect: org.bluez.Error.Failed br-connection-page-timeout"
            return Result(1, f"Attempting to connect to {mac}\n{failure}\n", "")
        raise AssertionError(f"unexpected bluetoothctl command: {command}")

    def _alias(self, mac: str) -> str:
        """BlueZ shows an unnamed device by its address with dashes."""
        return self.devices[mac].name or mac.replace(":", "-")

    def _info(self, mac: str, device: FakeDevice) -> str:
        lines = [f"Device {mac} (public)"]
        if device.name:
            lines.append(f"\tName: {device.name}")
        lines += [
            f"\tAlias: {self._alias(mac)}",
            "\tClass: 0x00240414 (2360340)",
            "\tIcon: audio-headset",
            f"\tPaired: {_yes(device.paired)}",
            f"\tBonded: {_yes(device.paired)}",
            f"\tTrusted: {_yes(device.trusted)}",
            "\tBlocked: no",
            f"\tConnected: {_yes(device.connected)}",
            "\tLegacyPairing: no",
            "\tUUID: Audio Sink                (0000110b-0000-1000-8000-00805f9b34fb)",
        ]
        return "\n".join(lines) + "\n"

    def _pactl(self, *args: str) -> Result:
        sinks = self._all_sinks()
        if args == ("list", "sinks", "short"):
            rows = [
                f"{index}\t{sink}\tPipeWire\ts16le 2ch 48000Hz\tSUSPENDED\n"
                for index, sink in enumerate(sinks)
            ]
            return Result(0, "".join(rows), "")
        if args[0] == "set-default-sink" and args[1] in sinks:
            self.default_sink = args[1]
            return Result(0, "", "")
        return Result(1, "", "Failure: No such entity\n")

    def _all_sinks(self) -> list[str]:
        """The fixed sinks plus one PipeWire sink per connected device."""
        speakers = [
            f"bluez_output.{mac.replace(':', '_')}.1"
            for mac, device in self.devices.items()
            if device.connected
        ]
        return self.sinks + speakers


@pytest.fixture
def system() -> FakeSystem:
    return FakeSystem()


@pytest.fixture
def bluez(system: FakeSystem) -> Bluez:
    return Bluez(system, session_factory=system.open_session)
