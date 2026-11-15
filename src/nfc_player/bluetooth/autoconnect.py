"""Speaker auto-connect service (nfc-player-bluetooth.service).

Connects the configured speakers in priority order and keeps the connected one: it never switches
to a higher-priority speaker while one is connected. rfkill is unblocked once by the unit's
ExecStartPre, never in this loop.
"""

import argparse
import logging
import signal
import threading
import time
from collections.abc import Callable, Sequence

from nfc_player.bluetooth.audio_sink import set_default_sink
from nfc_player.bluetooth.bluez import Bluez
from nfc_player.core import paths
from nfc_player.core.build_info import load_build_info
from nfc_player.core.config import ConfigError, Speaker, load_config
from nfc_player.core.log import setup_logging
from nfc_player.core.process import Runner, run

log = logging.getLogger(__name__)


class AutoConnect:
    def __init__(
        self,
        bluez: Bluez,
        load_speakers: Callable[[], Sequence[Speaker]],
        *,
        runner: Runner = run,
        check_interval: float = 10,
        reload_interval: float = 60,
        settle: float = 3,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._bluez = bluez
        self._load_speakers = load_speakers
        self._runner = runner
        self._check_interval = check_interval
        self._reload_interval = reload_interval
        self._settle = settle
        self._clock = clock
        self._sleep = sleep
        self._stop = threading.Event()  # run() replaces it with its own
        self._speakers: tuple[Speaker, ...] = ()
        self._loaded_at: float | None = None
        self.connected: Speaker | None = None

    def step(self) -> None:
        """One check: reload the speakers when due, keep the connection or connect the best speaker."""
        self._reload_when_due()
        if self.connected is not None:
            info = self._bluez.info(self.connected.mac)
            if info is not None and info.connected:
                return
            log.warning("Lost connection to %s (%s)", self.connected.name, self.connected.mac)
            self.connected = None
        if not self._speakers:
            return
        if not self._bluez.power_on():
            log.warning("Could not power on the Bluetooth adapter")
        for speaker in self._speakers:
            if self._stop.is_set():
                return
            if self._connect(speaker):
                self.connected = speaker
                return
        log.warning("Could not connect to any speaker, retrying in %g s", self._check_interval)

    def run(self, stop: threading.Event) -> None:
        """step() every check_interval until `stop` is set."""
        self._stop = stop
        while not stop.is_set():
            self.step()
            stop.wait(self._check_interval)

    def _reload_when_due(self) -> None:
        now = self._clock()
        first = self._loaded_at is None
        if not first and now - self._loaded_at < self._reload_interval:
            return
        self._loaded_at = now
        speakers = tuple(sorted(self._load_speakers(), key=lambda speaker: speaker.priority, reverse=True))
        if not first and speakers == self._speakers:
            return
        self._speakers = speakers
        if not speakers:
            log.info("No speakers configured, waiting for a config update")
            return
        log.info("Speakers by priority:")
        for speaker in speakers:
            log.info("  [priority %d] %s (%s)", speaker.priority, speaker.name, speaker.mac)
            self._bluez.trust(speaker.mac)  # a trusted speaker may also reconnect on its own

    def _connect(self, speaker: Speaker) -> bool:
        info = self._bluez.info(speaker.mac)
        if info is None or not info.paired:
            log.warning(
                "%s (%s) is not paired, pair it with: nfc-bt connect %s",
                speaker.name,
                speaker.mac,
                speaker.mac,
            )
            return False
        log.info("Trying %s (%s, priority %d)", speaker.name, speaker.mac, speaker.priority)
        self._bluez.connect(speaker.mac)
        self._sleep(self._settle)
        info = self._bluez.info(speaker.mac)
        if info is None or not info.connected:
            log.warning("Connection to %s (%s) failed", speaker.name, speaker.mac)
            return False
        log.info("Connected to %s (%s)", speaker.name, speaker.mac)
        set_default_sink(speaker.mac, self._runner, sleep=self._sleep)
        return True


def load_speakers() -> Sequence[Speaker]:
    """Speakers of the device config; none while it is missing or invalid."""
    try:
        return load_config(paths.DEVICE_CONFIG).speakers
    except FileNotFoundError:
        log.warning("%s not found, no speakers", paths.DEVICE_CONFIG)
    except (OSError, ConfigError) as exc:
        log.warning("%s unusable, no speakers: %s", paths.DEVICE_CONFIG, exc)
    return ()


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="Keep the configured Bluetooth speakers connected.").parse_args(argv)
    build = load_build_info()
    setup_logging(build.maturity)
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda _signum, _frame: stop.set())
    log.info("Speaker auto-connect %s started", build.version)
    # stop.wait as the sleep: a stop request also ends the settle waits early.
    AutoConnect(Bluez(), load_speakers, sleep=stop.wait).run(stop)
    log.info("Speaker auto-connect stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
