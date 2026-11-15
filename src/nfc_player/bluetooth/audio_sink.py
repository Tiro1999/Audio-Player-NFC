"""Default audio sink: route the audio server (PipeWire or PulseAudio) to a speaker.

The speaker's sink is found by its MAC: PipeWire names it bluez_output.<MAC>.<n>, PulseAudio
bluez_sink.<MAC>.a2dp_sink, both with "_" instead of ":".
"""

import logging
import time
from collections.abc import Callable

from nfc_player.core.process import Runner, run

log = logging.getLogger(__name__)


def find_sink(mac: str, runner: Runner = run) -> str | None:
    """Name of the speaker's sink: column 2 of `pactl list sinks short` contains the MAC with "_"."""
    result = runner(["pactl", "list", "sinks", "short"])
    if not result.ok:
        log.debug("pactl list sinks failed: %s", result.stderr.strip())
        return None
    needle = mac.upper().replace(":", "_")
    for line in result.stdout.split("\n"):
        columns = line.split()
        if len(columns) > 1 and needle in columns[1].upper():
            return columns[1]
    return None


def set_default_sink(
    mac: str, runner: Runner = run, *, settle: float = 2.0, sleep: Callable[[float], None] = time.sleep
) -> bool:
    """Make the speaker the default sink, after `settle` seconds for the audio server to add it."""
    sleep(settle)
    sink = find_sink(mac, runner)
    if sink is None:
        log.warning("No audio sink found for %s", mac)
        return False
    if not runner(["pactl", "set-default-sink", sink]).ok:
        log.warning("Could not make %s the default audio sink", sink)
        return False
    log.info("Default audio sink: %s", sink)
    return True
