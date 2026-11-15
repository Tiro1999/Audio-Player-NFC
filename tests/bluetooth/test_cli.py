"""Tests for nfc_player.bluetooth.cli (nfc-bt)."""

import json
import re

import pytest

from nfc_player.bluetooth import cli
from nfc_player.bluetooth.bluez import Bluez
from nfc_player.core import paths
from nfc_player.core.process import Result
from nfc_player.core.validate import speaker_name_error

MAC = "4C:87:5D:00:00:0A"
OTHER = "4C:87:5D:00:00:0B"
IMPORT = ("systemctl", "start", "nfc-player-config.service")


@pytest.fixture
def boot_config(monkeypatch, tmp_path, system):
    """BOOT_CONFIG in a temp dir; the CLI runs every command on the fake system."""
    path = tmp_path / "config.json"
    monkeypatch.setattr(paths, "BOOT_CONFIG", path)
    monkeypatch.setattr(cli, "run", system)
    monkeypatch.setattr(cli, "Bluez", lambda runner: Bluez(runner, session_factory=system.open_session))
    return path


def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path.read_bytes()


def saved_speakers(path):
    return json.loads(path.read_text(encoding="utf-8"))["bluetooth"]["speakers"]


def test_cli_connect_saves_only_when_paired(boot_config, system):
    before = write(boot_config, {"spotify": {"device_name": "Box"}})
    system.add_nearby(MAC, "JBL Flip 5", pairable=False)
    assert cli.main(["connect", MAC, "--priority", "7"]) == 1
    assert boot_config.read_bytes() == before
    assert IMPORT not in system.calls

    system.devices[MAC].pairable = True
    assert cli.main(["connect", MAC.lower(), "--priority", "7"]) == 0
    assert json.loads(boot_config.read_text(encoding="utf-8")) == {
        "spotify": {"device_name": "Box"},
        "bluetooth": {"speakers": [{"mac": MAC, "name": "JBL Flip 5", "priority": 7}]},
    }
    assert system.calls[-1] == IMPORT


@pytest.mark.parametrize(
    ("advertised", "saved"),
    [
        ("\x1b[2J Party\tBox " + "x" * 80, "[2J PartyBox " + "x" * 51),
        ("\x07\x07", MAC),
    ],
)
def test_cli_connect_sanitizes_name(boot_config, system, advertised, saved):
    system.add_nearby(MAC, advertised)
    assert cli.main(["connect", MAC]) == 0
    (speaker,) = saved_speakers(boot_config)
    assert speaker["name"] == saved
    assert speaker_name_error(speaker["name"]) is None


def test_cli_connect_by_name(boot_config, system):
    system.add(OTHER, "Kitchen speaker")
    system.add(MAC, "JBL Flip 5")
    assert cli.main(["connect", "flip", "--priority", "9"]) == 0
    assert saved_speakers(boot_config) == [{"mac": MAC, "name": "JBL Flip 5", "priority": 9}]


def test_cli_connect_unknown_name_exit_1(boot_config, system, capsys):
    system.add(OTHER, "Kitchen speaker")
    assert cli.main(["connect", "flip"]) == 1
    assert "nfc-bt scan" in capsys.readouterr().err
    assert system.sessions == []
    assert not boot_config.exists()


@pytest.mark.parametrize("priority", ["0", "11", "ten"])
def test_cli_priority_out_of_range_exit_2(boot_config, system, capsys, priority):
    assert cli.main(["connect", MAC, "--priority", priority]) == 2
    assert "--priority" in capsys.readouterr().err
    assert system.calls == []
    assert system.sessions == []


@pytest.mark.parametrize("speaker", ["AA:BB:CC:DD:EE:FF", " "])
def test_cli_connect_rejects_placeholder_or_empty_speaker(boot_config, system, speaker):
    assert cli.main(["connect", speaker]) == 2
    assert system.calls == []


def test_cli_connect_reports_a_failed_import(boot_config, system, capsys):
    system.add_nearby(MAC, "JBL Flip 5")
    system.overrides[IMPORT] = Result(1, "", "Job for nfc-player-config.service failed.\n")
    assert cli.main(["connect", MAC]) == 1
    assert saved_speakers(boot_config) == [{"mac": MAC, "name": "JBL Flip 5", "priority": 5}]
    assert "nfc-player-config" in capsys.readouterr().err


def test_cli_remove_without_section(boot_config, system, capsys):
    before = write(boot_config, {"spotify": {"device_name": "Box"}})
    assert cli.main(["remove", MAC]) == 1
    assert MAC in capsys.readouterr().out

    system.add(MAC, "JBL Flip 5", paired=True, trusted=True)
    assert cli.main(["remove", MAC, "--unpair"]) == 0
    assert MAC not in system.devices
    assert boot_config.read_bytes() == before
    assert IMPORT not in system.calls


def test_cli_remove_updates_boot_config(boot_config, system):
    kitchen = {"mac": OTHER, "name": "Kitchen", "priority": 3}
    write(boot_config, {"bluetooth": {"speakers": [{"mac": MAC, "name": "JBL", "priority": 5}, kitchen]}})
    assert cli.main(["remove", MAC.lower()]) == 0
    assert saved_speakers(boot_config) == [kitchen]
    assert system.calls == [IMPORT]


def test_cli_list_legacy_format(boot_config, capsys):
    write(boot_config, {"bluetooth": {"speaker_mac": "4c:87:5d:00:00:0a", "speaker_name": "Old Box"}})
    assert cli.main(["list"]) == 0
    assert re.search(r"10\s+4C:87:5D:00:00:0A\s+Old Box", capsys.readouterr().out)


def test_cli_list_ignores_errors_outside_bluetooth(boot_config, capsys):
    write(
        boot_config,
        {
            "wifi": [{"ssid": "Home", "priority": "10"}],
            "bluetooth": {"speakers": [{"mac": MAC, "name": "JBL", "priority": 5}]},
        },
    )
    assert cli.main(["list"]) == 0
    assert re.search(r"5\s+4C:87:5D:00:00:0A\s+JBL", capsys.readouterr().out)


def test_cli_list_invalid_json_exit_1(boot_config, capsys):
    boot_config.write_text('{"bluetooth": ', encoding="utf-8")
    assert cli.main(["list"]) == 1
    assert "invalid JSON" in capsys.readouterr().err


def test_cli_scan_lists_named_devices(boot_config, system, capsys):
    system.add_nearby(MAC, "JBL Flip 5")
    system.add_nearby("5A:11:22:33:44:55")
    assert cli.main(["scan", "--duration", "3"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"4C:87:5D:00:00:0A\s+JBL Flip 5", out)
    assert "5A:11:22:33:44:55" not in out
    assert system.sessions[0].waits == [3]
