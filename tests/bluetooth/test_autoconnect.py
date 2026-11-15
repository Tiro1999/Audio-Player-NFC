"""Tests for nfc_player.bluetooth.autoconnect."""

import json
import logging
import signal
import subprocess
import threading
import time

import pytest

from nfc_player.bluetooth import autoconnect
from nfc_player.bluetooth.autoconnect import AutoConnect
from nfc_player.bluetooth.bluez import Bluez
from nfc_player.core import paths
from nfc_player.core.build_info import SOURCE_BUILD
from nfc_player.core.config import Speaker

MAC_A = "4C:87:5D:00:00:0A"
MAC_B = "4C:87:5D:00:00:0B"
MAC_C = "4C:87:5D:00:00:0C"
HIGH = Speaker(MAC_A, "Living room", 10)
MIDDLE = Speaker(MAC_B, "Kitchen", 5)
LOW = Speaker(MAC_C, "Bath", 1)
LOGGER = "nfc_player.bluetooth.autoconnect"


def make(bluez, system, speakers):
    """AutoConnect on the fake system with fixed speakers; returns it and the list of its sleeps."""
    sleeps = []
    auto = AutoConnect(bluez, lambda: speakers, runner=system, sleep=sleeps.append)
    return auto, sleeps


def connects(system):
    return [call[2] for call in system.calls_of("bluetoothctl", "connect")]


def warnings(caplog):
    return [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]


def test_autoconnect_tries_priority_order(system, bluez):
    system.add(MAC_A, "Living room", paired=True, reachable=False)
    system.add(MAC_B, "Kitchen", paired=True)
    system.add(MAC_C, "Bath", paired=True)
    auto, sleeps = make(bluez, system, [LOW, MIDDLE, HIGH])
    auto.step()
    assert connects(system) == [MAC_A, MAC_B]
    assert auto.connected == MIDDLE
    assert system.default_sink == "bluez_output.4C_87_5D_00_00_0B.1"
    assert sleeps == [3, 3, 2]


def test_autoconnect_skips_unpaired_with_hint(system, bluez, caplog):
    system.add(MAC_B, "Kitchen")  # known to BlueZ, not paired; MAC_A is not known at all
    system.add(MAC_C, "Bath", paired=True)
    auto, _ = make(bluez, system, [HIGH, MIDDLE, LOW])
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        auto.step()
    assert connects(system) == [MAC_C]
    assert auto.connected == LOW
    hints = warnings(caplog)
    assert any(f"nfc-bt connect {MAC_A}" in message for message in hints)
    assert any(f"nfc-bt connect {MAC_B}" in message for message in hints)


def test_autoconnect_no_switch_while_connected(system, bluez):
    system.add(MAC_A, "Living room", paired=True, reachable=False)
    system.add(MAC_B, "Kitchen", paired=True)
    auto, _ = make(bluez, system, [HIGH, MIDDLE])
    auto.step()
    assert auto.connected == MIDDLE
    system.devices[MAC_A].reachable = True  # the preferred speaker comes back
    system.calls.clear()
    auto.step()
    auto.step()
    assert auto.connected == MIDDLE
    assert connects(system) == []


def test_autoconnect_warns_and_reconnects_after_a_lost_connection(system, bluez, caplog):
    system.add(MAC_A, "Living room", paired=True)
    system.add(MAC_B, "Kitchen", paired=True)
    auto, _ = make(bluez, system, [HIGH, MIDDLE])
    auto.step()
    assert auto.connected == HIGH
    system.devices[MAC_A].connected = False
    system.devices[MAC_A].reachable = False  # switched off
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        auto.step()
    assert any("lost" in message.lower() and MAC_A in message for message in warnings(caplog))
    assert auto.connected == MIDDLE


def test_autoconnect_reloads_after_interval(system, bluez):
    now = 0.0
    lists = iter([[HIGH], [HIGH], [HIGH, MIDDLE]])
    loads = []

    def load():
        loads.append(now)
        return next(lists)

    auto = AutoConnect(bluez, load, runner=system, clock=lambda: now, sleep=lambda seconds: None)
    auto.step()
    now = 59.0
    auto.step()
    now = 60.0
    auto.step()  # same speakers: nothing to trust again
    now = 120.0
    auto.step()  # a speaker was added: trust them all
    assert loads == [0.0, 60.0, 120.0]
    assert [call[2] for call in system.calls_of("bluetoothctl", "trust")] == [MAC_A, MAC_A, MAC_B]


def test_autoconnect_no_rfkill_calls(system, bluez, monkeypatch):
    def outside_the_runner(*args, **kwargs):
        raise AssertionError("subprocess started outside the runner")

    monkeypatch.setattr(subprocess, "run", outside_the_runner)
    monkeypatch.setattr(subprocess, "Popen", outside_the_runner)
    system.add(MAC_A, "Living room", paired=True)
    system.add(MAC_B, "Kitchen", paired=True, reachable=False)
    auto, _ = make(bluez, system, [HIGH, MIDDLE])
    auto.step()
    system.devices[MAC_A].connected = False
    auto.step()
    assert auto.connected == HIGH
    assert {call[0] for call in system.calls} == {"bluetoothctl", "pactl"}


def test_run_steps_until_stopped(system, bluez):
    stop = threading.Event()
    loads = []

    def load():
        loads.append(1)
        if len(loads) == 3:
            stop.set()
        return []

    AutoConnect(bluez, load, runner=system, check_interval=0.01, reload_interval=0).run(stop)
    assert len(loads) == 3


def test_run_returns_promptly_when_stopped_while_waiting(system, bluez):
    stop = threading.Event()
    timer = threading.Timer(0.05, stop.set)
    timer.start()
    started = time.monotonic()
    AutoConnect(bluez, lambda: [], runner=system, check_interval=60).run(stop)
    assert time.monotonic() - started < 5


def test_stop_request_skips_the_remaining_speakers(system, bluez):
    system.add(MAC_A, "Living room", paired=True, reachable=False)
    system.add(MAC_B, "Kitchen", paired=True)
    stop = threading.Event()
    auto = AutoConnect(bluez, lambda: [HIGH, MIDDLE], runner=system, sleep=lambda seconds: stop.set())
    auto.run(stop)
    assert connects(system) == [MAC_A]
    assert auto.connected is None


def test_load_speakers_reads_the_device_config(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    entries = [
        {"mac": MAC_B, "name": "Kitchen", "priority": 5},
        {"mac": MAC_A, "name": "Living room", "priority": 10},
    ]
    path.write_text(json.dumps({"bluetooth": {"speakers": entries}}), encoding="utf-8")
    monkeypatch.setattr(paths, "DEVICE_CONFIG", path)
    assert list(autoconnect.load_speakers()) == [HIGH, MIDDLE]


@pytest.mark.parametrize("content", [None, '{"bluetooth": '])
def test_load_speakers_without_usable_config_warns(monkeypatch, tmp_path, caplog, content):
    path = tmp_path / "config.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(paths, "DEVICE_CONFIG", path)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert list(autoconnect.load_speakers()) == []
    assert warnings(caplog)


def test_main_stops_on_sigterm(monkeypatch, system):
    handlers = {}
    monkeypatch.setattr(signal, "signal", lambda signum, handler: handlers.setdefault(signum, handler))
    monkeypatch.setattr(autoconnect, "load_build_info", lambda: SOURCE_BUILD)
    monkeypatch.setattr(autoconnect, "setup_logging", lambda maturity: None)
    monkeypatch.setattr(autoconnect, "Bluez", lambda: Bluez(system))

    def load_then_sigterm():
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        return []

    monkeypatch.setattr(autoconnect, "load_speakers", load_then_sigterm)
    started = time.monotonic()
    assert autoconnect.main([]) == 0
    assert time.monotonic() - started < 5
    assert set(handlers) == {signal.SIGTERM, signal.SIGINT}
