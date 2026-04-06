"""Bluetooth speaker auto-connect manager.

Uses the ``bluetoothctl`` CLI tool (part of *BlueZ*) to connect and
auto-reconnect to the configured speaker.

Why MAC address instead of device name?
----------------------------------------
Scanning by name is unreliable – if two people both have a "JBL Flip 5" the
Pi might connect to the wrong one.  After the initial pairing (``setup/install.sh``
guides the user through ``bluetoothctl pair <mac>``), the MAC address is
stable and deterministic.

Auto-reconnect strategy
-----------------------
A companion systemd service (``bt-connect.service``) runs ``setup/bt-connect.sh``
in a loop.  This module provides the same logic in pure Python for use in the
main application process (health-check thread) and for unit-testability.
"""

import logging
import subprocess
import time
from threading import Event, Thread

logger = logging.getLogger(__name__)


def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str, str]:
    """Run *cmd* and return *(returncode, stdout, stderr)*."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger.warning("Command %s timed out after %ds", cmd, timeout)
        return -1, "", "timeout"
    except FileNotFoundError:
        logger.error("Command not found: %s", cmd[0])
        return -1, "", "not found"


class BluetoothManager:
    """Manage the connection to a single paired Bluetooth audio device.

    Parameters
    ----------
    mac_address:
        Bluetooth MAC address of the target device (e.g. ``AA:BB:CC:DD:EE:FF``).
    device_name:
        Human-readable name used only for log messages.
    reconnect_interval:
        Seconds between reconnect attempts when not connected.
    """

    def __init__(
        self,
        mac_address: str,
        device_name: str = "Bluetooth Speaker",
        reconnect_interval: float = 10.0,
    ) -> None:
        self._mac = mac_address.upper()
        self._name = device_name
        self._interval = reconnect_interval
        self._stop_event = Event()
        self._thread: Thread | None = None

    # ------------------------------------------------------------------
    # Low-level bluetoothctl helpers
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Return *True* if the device is currently connected."""
        rc, stdout, _ = _run(["bluetoothctl", "info", self._mac])
        return rc == 0 and "Connected: yes" in stdout

    def connect(self) -> bool:
        """Attempt a single connect; return *True* on success."""
        logger.info("Connecting to %s (%s)…", self._name, self._mac)
        rc, stdout, _ = _run(["bluetoothctl", "connect", self._mac], timeout=15)
        success = rc == 0 and "Connection successful" in stdout
        if success:
            logger.info("Connected to %s (%s)", self._name, self._mac)
        else:
            logger.debug("Connect attempt failed for %s", self._mac)
        return success

    def trust(self) -> bool:
        """Mark the device as *trusted* so BlueZ reconnects automatically."""
        rc, _, _ = _run(["bluetoothctl", "trust", self._mac])
        return rc == 0

    # ------------------------------------------------------------------
    # Background reconnect loop
    # ------------------------------------------------------------------

    def _reconnect_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self.is_connected():
                self.connect()
            self._stop_event.wait(self._interval)

    def start_reconnect_loop(self) -> None:
        """Start a background thread that keeps the device connected."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(
            target=self._reconnect_loop,
            name="bt-reconnect",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Bluetooth reconnect loop started for %s (%s), interval=%ds",
            self._name,
            self._mac,
            int(self._interval),
        )

    def stop_reconnect_loop(self) -> None:
        """Stop the background reconnect thread gracefully."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self._interval + 2)
            self._thread = None

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config: dict) -> "BluetoothManager":
        """Construct a :class:`BluetoothManager` from the app config dict."""
        bt_cfg = config["bluetooth"]
        return cls(
            mac_address=bt_cfg["mac_address"],
            device_name=bt_cfg.get("device_name", "Bluetooth Speaker"),
            reconnect_interval=float(bt_cfg.get("reconnect_interval_seconds", 10)),
        )
