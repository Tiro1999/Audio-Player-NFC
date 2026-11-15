"""Tests for nfc_player.bluetooth.audio_sink."""

import pytest

from nfc_player.bluetooth.audio_sink import find_sink, set_default_sink
from nfc_player.core.process import Result

MAC = "4C:87:5D:00:00:0A"
ALSA_ROW = "47\talsa_output.platform-bcm2835_audio.stereo-fallback\tPipeWire\ts16le 2ch 48000Hz\tSUSPENDED\n"


def sinks_runner(output, calls=None):
    def runner(args, **kwargs):
        if calls is not None:
            calls.append(list(args))
        return Result(0, output, "")

    return runner


@pytest.mark.parametrize(
    "sink",
    ["bluez_output.AA_BB_CC_DD_EE_FF.1", "bluez_sink.AA_BB_CC_DD_EE_FF.a2dp_sink"],
)
def test_find_sink_pipewire_and_pulse_names(sink):
    calls = []
    runner = sinks_runner(f"{ALSA_ROW}58\t{sink}\tPipeWire\ts16le 2ch 48000Hz\tRUNNING\n", calls)
    assert find_sink("aa:bb:cc:dd:ee:ff", runner) == sink
    assert calls == [["pactl", "list", "sinks", "short"]]


def test_find_sink_ignores_other_speakers():
    other = "58\tbluez_output.11_22_33_44_55_66.1\tPipeWire\ts16le 2ch 48000Hz\tRUNNING\n"
    assert find_sink("AA:BB:CC:DD:EE:FF", sinks_runner(ALSA_ROW + other)) is None


def test_set_default_sink_not_found_false(system):
    sleeps = []
    assert set_default_sink(MAC, system, sleep=sleeps.append) is False
    assert sleeps == [2.0]
    assert system.calls_of("pactl", "set-default-sink") == []


def test_set_default_sink_routes_audio_to_the_speaker(system):
    system.add(MAC, "JBL Flip 5", paired=True, connected=True)
    sleeps = []
    assert set_default_sink(MAC, system, settle=0.5, sleep=sleeps.append) is True
    assert sleeps == [0.5]
    assert system.default_sink == "bluez_output.4C_87_5D_00_00_0A.1"


def test_set_default_sink_failure_false(system):
    system.add(MAC, "JBL Flip 5", paired=True, connected=True)
    sink = "bluez_output.4C_87_5D_00_00_0A.1"
    system.overrides[("pactl", "set-default-sink", sink)] = Result(1, "", "Failure: Access denied\n")
    assert set_default_sink(MAC, system, sleep=lambda seconds: None) is False
