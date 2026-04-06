"""Tests for src/bluetooth_manager.py."""

import time
from threading import Event
from unittest.mock import MagicMock, call, patch

import pytest

from src.bluetooth_manager import BluetoothManager, _run


# ── _run helper ───────────────────────────────────────────────────────────────

class TestRunHelper:
    def test_returns_stdout_on_success(self):
        rc, stdout, stderr = _run(["echo", "hello"])
        assert rc == 0
        assert "hello" in stdout

    def test_returns_nonzero_rc_on_failure(self):
        rc, stdout, stderr = _run(["false"])
        assert rc != 0

    def test_handles_timeout(self):
        rc, stdout, stderr = _run(["sleep", "60"], timeout=1)
        assert rc == -1
        assert "timeout" in stderr

    def test_handles_missing_command(self):
        rc, stdout, stderr = _run(["nonexistent_command_xyz"])
        assert rc == -1
        assert "not found" in stderr


# ── BluetoothManager ──────────────────────────────────────────────────────────

MAC = "AA:BB:CC:DD:EE:FF"
NAME = "Test Speaker"


def _make_manager(**kwargs) -> BluetoothManager:
    defaults = dict(mac_address=MAC, device_name=NAME, reconnect_interval=0.1)
    defaults.update(kwargs)
    return BluetoothManager(**defaults)


class TestIsConnected:
    def test_returns_true_when_bluetoothctl_shows_connected(self):
        mgr = _make_manager()
        with patch("src.bluetooth_manager._run") as mock_run:
            mock_run.return_value = (0, "Connected: yes\n", "")
            assert mgr.is_connected() is True

    def test_returns_false_when_not_connected(self):
        mgr = _make_manager()
        with patch("src.bluetooth_manager._run") as mock_run:
            mock_run.return_value = (0, "Connected: no\n", "")
            assert mgr.is_connected() is False

    def test_returns_false_on_nonzero_returncode(self):
        mgr = _make_manager()
        with patch("src.bluetooth_manager._run") as mock_run:
            mock_run.return_value = (1, "", "Device not found")
            assert mgr.is_connected() is False


class TestConnect:
    def test_returns_true_on_successful_connection(self):
        mgr = _make_manager()
        with patch("src.bluetooth_manager._run") as mock_run:
            mock_run.return_value = (0, "Connection successful\n", "")
            assert mgr.connect() is True

    def test_returns_false_on_failed_connection(self):
        mgr = _make_manager()
        with patch("src.bluetooth_manager._run") as mock_run:
            mock_run.return_value = (1, "Failed to connect", "")
            assert mgr.connect() is False

    def test_connect_calls_bluetoothctl_with_mac(self):
        mgr = _make_manager()
        with patch("src.bluetooth_manager._run") as mock_run:
            mock_run.return_value = (0, "Connection successful", "")
            mgr.connect()
            mock_run.assert_called_once_with(
                ["bluetoothctl", "connect", MAC], timeout=15
            )


class TestTrust:
    def test_returns_true_on_success(self):
        mgr = _make_manager()
        with patch("src.bluetooth_manager._run") as mock_run:
            mock_run.return_value = (0, "", "")
            assert mgr.trust() is True

    def test_returns_false_on_failure(self):
        mgr = _make_manager()
        with patch("src.bluetooth_manager._run") as mock_run:
            mock_run.return_value = (1, "", "error")
            assert mgr.trust() is False


class TestReconnectLoop:
    def test_connect_called_when_not_connected(self):
        mgr = _make_manager(reconnect_interval=0.05)
        call_count = {"n": 0}

        def fake_is_connected():
            return False

        def fake_connect():
            call_count["n"] += 1
            return True

        mgr.is_connected = fake_is_connected
        mgr.connect = fake_connect

        mgr.start_reconnect_loop()
        time.sleep(0.2)
        mgr.stop_reconnect_loop()

        assert call_count["n"] >= 2, "connect should have been called multiple times"

    def test_connect_not_called_when_already_connected(self):
        mgr = _make_manager(reconnect_interval=0.05)
        call_count = {"n": 0}

        mgr.is_connected = lambda: True
        mgr.connect = lambda: call_count.__setitem__("n", call_count["n"] + 1) or True

        mgr.start_reconnect_loop()
        time.sleep(0.2)
        mgr.stop_reconnect_loop()

        assert call_count["n"] == 0

    def test_start_is_idempotent(self):
        """Calling start_reconnect_loop twice should not start two threads."""
        mgr = _make_manager(reconnect_interval=0.1)
        mgr.is_connected = lambda: True
        mgr.start_reconnect_loop()
        thread1 = mgr._thread
        mgr.start_reconnect_loop()
        thread2 = mgr._thread
        assert thread1 is thread2
        mgr.stop_reconnect_loop()

    def test_stop_terminates_thread(self):
        mgr = _make_manager(reconnect_interval=0.05)
        mgr.is_connected = lambda: True
        mgr.start_reconnect_loop()
        assert mgr._thread is not None and mgr._thread.is_alive()
        mgr.stop_reconnect_loop()
        assert mgr._thread is None


# ── from_config ───────────────────────────────────────────────────────────────

class TestFromConfig:
    def test_constructs_from_valid_config(self):
        config = {
            "bluetooth": {
                "mac_address": "11:22:33:44:55:66",
                "device_name": "My Speaker",
                "reconnect_interval_seconds": 15,
            }
        }
        mgr = BluetoothManager.from_config(config)
        assert mgr._mac == "11:22:33:44:55:66"
        assert mgr._name == "My Speaker"
        assert mgr._interval == 15.0

    def test_uses_default_interval_when_missing(self):
        config = {
            "bluetooth": {
                "mac_address": "11:22:33:44:55:66",
            }
        }
        mgr = BluetoothManager.from_config(config)
        assert mgr._interval == 10.0
