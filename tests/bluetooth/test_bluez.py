"""Tests for nfc_player.bluetooth.bluez."""

import sys

import pytest

from nfc_player.bluetooth.bluez import Bluez, BluetoothctlSession, DeviceInfo, is_random_ble_name
from nfc_player.core.process import Result

MAC_A = "4C:87:5D:00:00:0A"
MAC_B = "4C:87:5D:00:00:0B"
MAC_C = "4C:87:5D:00:00:0C"
MAC_BLE = "5A:11:22:33:44:55"

# Shape of `bluetoothctl info` (BlueZ 5.82) for a paired, connected, untrusted speaker.
INFO_OUTPUT = """\
Device 4C:87:5D:00:00:0A (public)
\tName: JBL Flip 5
\tAlias: Party Box
\tClass: 0x00240414 (2360340)
\tIcon: audio-headset
\tPaired: yes
\tBonded: yes
\tTrusted: no
\tBlocked: no
\tConnected: yes
\tWakeAllowed: no
\tLegacyPairing: no
\tUUID: Audio Sink                (0000110b-0000-1000-8000-00805f9b34fb)
\tUUID: A/V Remote Control Target (0000110c-0000-1000-8000-00805f9b34fb)
\tModalias: bluetooth:v000Fp1200d1436
"""


def test_info_parses_flags():
    calls = []

    def runner(args, **kwargs):
        calls.append(list(args))
        return Result(0, INFO_OUTPUT, "")

    info = Bluez(runner).info(MAC_A)
    assert info == DeviceInfo(MAC_A, "JBL Flip 5", paired=True, trusted=False, connected=True)
    assert calls == [["bluetoothctl", "info", MAC_A]]


def test_info_unknown_device_is_none():
    assert Bluez(lambda args, **kwargs: Result(1, f"Device {MAC_A} not available\n", "")).info(MAC_A) is None


def test_info_unnamed_device_has_no_name(system, bluez):
    system.add(MAC_BLE)
    assert bluez.info(MAC_BLE) == DeviceInfo(MAC_BLE, None, paired=False, trusted=False, connected=False)


def test_info_removes_terminal_escapes_from_the_name(system, bluez):
    system.add(MAC_A, "\x1b[2JJBL‮ Flip")
    assert bluez.info(MAC_A).name == "[2JJBL Flip"


def test_connect_allows_15_s():
    seen = []

    def runner(args, *, timeout=None, **kwargs):
        seen.append((list(args), timeout))
        return Result(0, "Connection successful\n", "")

    assert Bluez(runner).connect(MAC_A) is True
    assert seen == [(["bluetoothctl", "connect", MAC_A], 15)]


def test_devices_lists_known_devices(system, bluez):
    system.add(MAC_A, "JBL Flip 5", paired=True)
    system.add(MAC_BLE)
    assert bluez.devices() == [(MAC_A, "JBL Flip 5"), (MAC_BLE, "5A-11-22-33-44-55")]


def test_scan_keeps_paired_and_trusted_devices(system, bluez):
    system.add(MAC_A, "Paired speaker", paired=True)
    system.add(MAC_B, "Trusted speaker", trusted=True)
    system.add(MAC_C, "Stale device")
    bluez.scan(10)
    assert system.calls_of("bluetoothctl", "remove") == [("bluetoothctl", "remove", MAC_C)]


def test_scan_runs_a_bredr_session_and_returns_named_devices(system, bluez):
    system.add(MAC_A, "Kitchen", paired=True)
    system.add_nearby(MAC_B, "JBL Flip 5")
    system.add_nearby(MAC_BLE)  # unnamed: BlueZ shows 5A-11-22-33-44-55
    found = bluez.scan(12)
    (session,) = system.sessions
    assert session.sent == ["menu scan", "transport bredr", "back", "scan on", "scan off"]
    assert session.waits == [12]
    assert session.closed
    assert found == [(MAC_A, "Kitchen"), (MAC_B, "JBL Flip 5")]


def test_scan_closes_the_session_when_interrupted(system):
    def interrupted_session():
        session = system.open_session()

        def wait(seconds):
            raise KeyboardInterrupt

        session.wait = wait
        return session

    with pytest.raises(KeyboardInterrupt):
        Bluez(system, session_factory=interrupted_session).scan(10)
    assert system.sessions[0].closed


def test_pair_trust_connect_keeps_the_session_timings(system, bluez):
    system.add_nearby(MAC_A, "JBL Flip 5")
    info = bluez.pair_trust_connect(MAC_A.lower())
    (session,) = system.sessions
    assert session.sent == [
        "menu scan",
        "transport bredr",
        "back",
        "scan on",
        "scan off",
        f"pair {MAC_A}",
        f"trust {MAC_A}",
        f"connect {MAC_A}",
    ]
    assert session.waits == [8, 8, 1, 5]
    assert session.closed
    assert info == DeviceInfo(MAC_A, "JBL Flip 5", paired=True, trusted=True, connected=True)


def test_pair_trust_connect_device_not_found(system, bluez):
    info = bluez.pair_trust_connect(MAC_A)
    assert info == DeviceInfo(MAC_A, None, paired=False, trusted=False, connected=False)
    assert system.sessions[0].closed


def test_pair_trust_connect_rejects_extra_session_commands(system, bluez):
    with pytest.raises(ValueError):
        bluez.pair_trust_connect(f"{MAC_A}\nremove {MAC_B}")
    assert system.sessions == []


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("5A-11-22-33-44-55", True),
        ("5A:11:22:33:44:55", True),
        ("5a-11-22-33-44-55", True),
        ("5A-11-22-33-44-56", False),
        ("JBL Flip 5", False),
    ],
)
def test_is_random_ble_name(name, expected):
    assert is_random_ble_name(name, MAC_BLE) is expected


def test_bluetoothctl_session_sends_lines_and_exit(tmp_path):
    received = tmp_path / "stdin.txt"
    record_stdin = "import pathlib, sys; pathlib.Path(sys.argv[1]).write_text(sys.stdin.read())"
    session = BluetoothctlSession([sys.executable, "-c", record_stdin, str(received)])
    session.send("menu scan", "scan on")
    session.wait(0.01)
    session.send("scan off")
    session.close()
    assert received.read_text() == "menu scan\nscan on\nscan off\nexit\n"
