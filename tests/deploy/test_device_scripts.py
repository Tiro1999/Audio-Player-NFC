"""Device side (deploy/device/): script syntax, shellcheck, unit hardening,
network safety, polkit scope, and install-release.sh / run-detached.sh
exercised with stub systemctl, systemd-run and journalctl on PATH."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DEVICE = REPO / "deploy" / "device"
INSTALL_RELEASE = DEVICE / "install-release.sh"
RUN_DETACHED = DEVICE / "run-detached.sh"

EXPECTED_SCRIPTS = [
    "lib.sh",
    "provision.sh",
    "install-release.sh",
    "run-detached.sh",
    "base/setup.sh",
    "nfc/setup.sh",
    "spotify/setup.sh",
    "wifi/setup.sh",
    "bluetooth/setup.sh",
    "update/setup.sh",
    "app/bin/nfc-log",
    "app/bin/nfc-status",
    "app/bin/nfc-restart",
    "app/profile.d/nfc-player.sh",
    "spotify/bin/nfc-test",
    "wifi/bin/nfc-wifi",
    "bluetooth/bin/nfc-bt",
]

PYTHON = "/opt/nfc-player/current/venv/bin/python"
ROOT_ONESHOTS = {"nfc-player-config.service", "nfc-player-update.service"}

LOCK = b"example==1.0 \\\n    --hash=sha256:" + b"0" * 64 + b"\n"
REV = "ab" * 32
UID = "4242"
OLD_CURRENT = "releases/20260104-000000-v0.0.4"
OLD_PREVIOUS = "releases/20260103-000000-v0.0.3"
NEW_RELEASE = re.compile(r"releases/\d{8}-\d{6}-v1\.0\.0")
OLD_RELEASES = {
    "20260101-000000-v0.0.1": (["spotify"], "bbbbbbbbbbbb"),
    "20260102-000000-v0.0.2": (["spotify"], "bbbbbbbbbbbb"),
    "20260103-000000-v0.0.3": (["spotify", "bluetooth"], "aaaaaaaaaaaa"),
    "20260104-000000-v0.0.4": (["spotify", "bluetooth"], "aaaaaaaaaaaa"),
}

SYSTEMCTL_STUB = r"""#!/usr/bin/env bash
# Test stub: records each call; units are active unless named in STUB_FAILED_UNIT.
printf '%s\n' "$*" >> "$STUB_LOG"
if [[ "$1" == show ]]; then
    unit="${*: -1}"
    case "$*" in
        *ActiveState*) if [[ "$unit" == "${STUB_FAILED_UNIT:-}" ]]; then echo failed; else echo active; fi ;;
        *NRestarts*) echo 0 ;;
    esac
fi
exit 0
"""

PROVISION_STUB = r"""#!/usr/bin/env bash
# Test stand-in for provision.sh: only records that it ran.
printf 'ran\n' > "$STUB_PROVISION_MARKER"
"""

SYSTEMD_RUN_STUB = r"""#!/usr/bin/env bash
# Test stub: applies --setenv, skips the other options, runs the command at once.
while [[ "$1" == -* ]]; do
    if [[ "$1" == --setenv=* ]]; then export "${1#--setenv=}"; fi
    shift
done
"$@" > "$STUB_JOURNAL" 2>&1 || true
"""

JOURNALCTL_STUB = r"""#!/usr/bin/env bash
# Test stub: prints what the unit wrote, then follows until it is killed.
cat "$STUB_JOURNAL"
exec sleep 30
"""

INACTIVE_SYSTEMCTL_STUB = r"""#!/usr/bin/env bash
# Test stub: every unit is inactive.
if [[ "$1" == show ]]; then echo inactive; fi
if [[ "$1" == is-active ]]; then exit 3; fi
exit 0
"""

SETUP_STUB = r"""#!/usr/bin/env bash
# Test stand-in for a setup.sh: records its module and the provisioning options.
echo "$(basename "$(dirname "$0")") $PROVISION_OS_UPGRADE $PROVISION_USB_GADGET" \
    "$PROVISION_WPASUPPLICANT ${PROVISION_I2C_BAUDRATE:--} $PROVISION_SSH_HARDENING" >>"$STUB_LOG"
"""


# --- helpers -----------------------------------------------------------------


def shell_scripts() -> list[Path]:
    """Every *.sh file plus every file in a */bin/ directory."""
    scripts = set(DEVICE.rglob("*.sh"))
    scripts.update(path for path in DEVICE.glob("*/bin/*") if path.is_file())
    return sorted(scripts)


def find_shellcheck() -> str | None:
    """shellcheck on PATH, else the one installed beside this Python (shellcheck-py)."""
    found = shutil.which("shellcheck")
    if found:
        return found
    beside = Path(sys.executable).with_name("shellcheck")
    return str(beside) if beside.exists() else None


def unit_settings(path: Path) -> dict[str, list[str]]:
    """Key → values of a unit file, all sections merged."""
    settings: dict[str, list[str]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";", "[")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        settings.setdefault(key.strip(), []).append(value.strip())
    return settings


def clean_env(**extra: str) -> dict[str, str]:
    """The test process environment without NFC_*/STUB_* variables, plus extra."""
    env = {key: value for key, value in os.environ.items() if not key.startswith(("NFC_", "STUB_"))}
    env.update(extra)
    return env


def write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def bundle_members(version: str, modules: list[str], **build_info: object) -> dict[str, tuple[bytes, int]]:
    """Bundle content like deploy/bundle.py builds it; provision.sh is a recorder."""
    info = {
        "version": version,
        "maturity": "dev",
        "modules": modules,
        "built": "2026-11-13T12:00:00Z",
        "provision_rev": REV,
        **build_info,
    }
    members = {
        "build_info.json": (json.dumps(info).encode(), 0o644),
        "src/nfc_player/__init__.py": (b"", 0o644),
        "requirements/device.lock": (LOCK, 0o644),
    }
    for path in sorted(DEVICE.rglob("*")):
        relative = path.relative_to(DEVICE)
        module = relative.parts[0] if len(relative.parts) > 1 else None
        if not path.is_file() or module not in (None, "base", "app", *modules):
            continue
        executable = path.suffix == ".sh" or relative.parent.name in ("bin", "profile.d")
        members[f"device/{relative.as_posix()}"] = (path.read_bytes(), 0o755 if executable else 0o644)
    members["device/provision.sh"] = (PROVISION_STUB.encode(), 0o755)
    return members


def write_bundle(path: Path, members: dict[str, tuple[bytes, int]]) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        for name, (data, mode) in sorted(members.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = mode
            tar.addfile(info, io.BytesIO(data))
    return path


class FakeDevice:
    """Temp install root, unit/bin/profile/etc dirs and a systemctl stub on PATH."""

    def __init__(self, tmp: Path) -> None:
        self.root = tmp / "opt"
        self.units = tmp / "units"
        self.bin = tmp / "bin"
        self.profile = tmp / "profile.d"
        self.etc = tmp / "etc"
        self.stubs = tmp / "stubs"
        self.log = tmp / "systemctl.log"
        self.marker = tmp / "provisioned"
        for directory in (self.root, self.units, self.bin, self.profile, self.etc, self.stubs):
            directory.mkdir(parents=True)
        (self.etc / "provision-rev").write_text(REV + "\n", encoding="utf-8")
        write_executable(self.stubs / "systemctl", SYSTEMCTL_STUB)

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        """Runs install-release.sh; env entries override the defaults below."""
        defaults = {
            "PATH": f"{self.stubs}{os.pathsep}{os.environ.get('PATH', '')}",
            "NFC_INSTALL_ROOT": str(self.root),
            "NFC_UNIT_DIR": str(self.units),
            "NFC_BIN_DIR": str(self.bin),
            "NFC_PROFILE_DIR": str(self.profile),
            "NFC_ETC_DIR": str(self.etc),
            "NFC_SKIP_VENV": "1",
            "NFC_SKIP_ROOT_CHECK": "1",
            "NFC_HEALTH_SECONDS": "0",
            "NFC_UID": UID,
            "STUB_LOG": str(self.log),
            "STUB_PROVISION_MARKER": str(self.marker),
        }
        full_env = clean_env(**(defaults | env))
        return subprocess.run(
            ["bash", str(INSTALL_RELEASE), *args],
            env=full_env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    def link(self, name: str) -> str:
        return os.readlink(self.root / name)

    def calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def releases(self) -> set[str]:
        releases = self.root / "releases"
        return {path.name for path in releases.iterdir() if path.is_dir()} if releases.exists() else set()


def seed_old_releases(dev: FakeDevice) -> None:
    """Four releases installed earlier; current and previous ship bluetooth."""
    for release_id, (modules, venv) in OLD_RELEASES.items():
        release = dev.root / "releases" / release_id
        for name, (data, mode) in bundle_members(release_id.rsplit("-", 1)[1], modules).items():
            target = release / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(mode)
        (release / "venv").symlink_to(f"../../venvs/{venv}")
    for venv in ("aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc"):
        (dev.root / "venvs" / venv).mkdir(parents=True)
    (dev.root / "current").symlink_to(OLD_CURRENT)
    (dev.root / "previous").symlink_to(OLD_PREVIOUS)
    # Installed for the old current release; the new bundle drops bluetooth.
    (dev.units / "nfc-player-bluetooth.service").write_text("[Service]\nUser=nfc-player\n", encoding="utf-8")
    write_executable(dev.bin / "nfc-bt", "#!/bin/sh\n")
    # Files the install does not own must survive.
    write_executable(dev.bin / "nfc-list", "#!/bin/sh\n")
    (dev.units / "foreign.service").write_text("[Service]\n", encoding="utf-8")


# --- static checks -----------------------------------------------------------


def test_shell_scripts_parse():
    scripts = shell_scripts()
    missing = [name for name in EXPECTED_SCRIPTS if DEVICE / name not in scripts]
    assert not missing, f"missing scripts: {missing}"
    for script in scripts:
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, f"{script.relative_to(REPO)}: {result.stderr}"


def test_shellcheck_clean():
    shellcheck = find_shellcheck()
    if shellcheck is None:
        pytest.skip("shellcheck not installed")
    scripts = [str(path) for path in shell_scripts()]
    assert scripts
    # -x follows lib.sh; the plain run matches CI, which does not follow sources.
    for follow in (["-x"], []):
        result = subprocess.run(
            [shellcheck, *follow, "-S", "warning", *scripts], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_units_hardened():
    units = sorted(DEVICE.glob("*/systemd/nfc-player*.service"))
    assert {unit.name for unit in units} >= ROOT_ONESHOTS | {
        "nfc-player.service",
        "nfc-player-receiver.service",
        "nfc-player-bluetooth.service",
    }
    for unit in units:
        settings = unit_settings(unit)
        root_oneshot = settings.get("Type") == ["oneshot"] and "User" not in settings
        assert root_oneshot == (unit.name in ROOT_ONESHOTS), unit.name
        if root_oneshot:
            continue
        assert settings.get("User") == ["nfc-player"], unit.name
        assert settings.get("NoNewPrivileges") == ["yes"], unit.name
        assert settings.get("TimeoutStopSec") == ["15"], unit.name


def test_units_run_contract_entry_points():
    expected = {
        "nfc-player.service": ("ExecStart", "nfc_player"),
        "nfc-player-config.service": ("ExecStart", "nfc_player.app.config_import"),
        "nfc-player-receiver.service": ("ExecStartPre", "nfc_player.spotify.receiver_config"),
        "nfc-player-bluetooth.service": ("ExecStart", "nfc_player.bluetooth.autoconnect"),
        "nfc-player-update.service": ("ExecStart", "nfc_player.update.github"),
    }
    units = {path.name: path for path in DEVICE.glob("*/systemd/*")}
    for name, (key, module) in expected.items():
        settings = unit_settings(units[name])
        assert settings.get(key) == [f"{PYTHON} -m {module}"], name
        assert "PYTHONPATH=/opt/nfc-player/current/src" in " ".join(settings.get("Environment", [])), name
    receiver = unit_settings(units["nfc-player-receiver.service"])
    assert receiver["ExecStart"] == [
        "/opt/nfc-player/receiver/go-librespot --config_dir /var/lib/nfc-player/receiver"
    ]
    timer = unit_settings(DEVICE / "update/systemd/nfc-player-update.timer")
    assert timer["OnBootSec"] == ["3min"]
    assert timer["Unit"] == ["nfc-player-update.service"]


def test_wrappers_call_contract_modules():
    expected = {
        "spotify/bin/nfc-test": ("exec sudo -u nfc-player ", "nfc_player.spotify.cli"),
        "wifi/bin/nfc-wifi": ("exec sudo ", "nfc_player.wifi.cli"),
        "bluetooth/bin/nfc-bt": ("exec sudo ", "nfc_player.bluetooth.cli"),
    }
    for name, (runner, module) in expected.items():
        text = (DEVICE / name).read_text(encoding="utf-8")
        assert runner in text, name
        assert f'-m {module} "$@"' in text, name
    nfc_log = (DEVICE / "app/bin/nfc-log").read_text(encoding="utf-8")
    assert "exec journalctl -f -u 'nfc-player*' \"$@\"" in nfc_log


def test_no_network_disruption_commands():
    forbidden = (
        "restart NetworkManager",
        "nmcli radio",
        "nmcli connection up",
        "nmcli connection down",
        "nmcli device disconnect",
        "systemctl restart ssh",
    )
    files = [path for path in DEVICE.rglob("*") if path.is_file()]
    assert files
    for path in files:
        flat = " ".join(path.read_text(encoding="utf-8").replace("\\\n", " ").split()).lower()
        for phrase in forbidden:
            assert phrase.lower() not in flat, f"{path.relative_to(REPO)} contains {phrase!r}"


def test_polkit_rule_scoped_to_user():
    text = (DEVICE / "wifi/50-nfc-player-networkmanager.rules").read_text(encoding="utf-8")
    assert re.search(r'subject\.user\s*===?\s*"nfc-player"', text)
    assert set(re.findall(r'"(org\.freedesktop\.[\w.-]+)"', text)) == {
        "org.freedesktop.NetworkManager.settings.modify.system",
        "org.freedesktop.NetworkManager.network-control",
        "org.freedesktop.NetworkManager.wifi.scan",
    }
    assert text.count("polkit.Result.YES") == 1
    for broad in ("isInGroup", "startsWith", 'indexOf("org.freedesktop', "subject.local", "subject.active"):
        assert broad not in text, broad


# --- provision.sh and run-detached.sh ----------------------------------------


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ([], "build_info.json"),
        (["--bogus"], "usage"),
        (["--hold-wpasupplicant", "--release-wpasupplicant"], "usage"),
        (["--i2c-baudrate", "fast"], "baudrate"),
    ],
)
def test_provision_rejects_bad_input_before_any_change(tmp_path, args, message):
    device = tmp_path / "device"
    device.mkdir()
    for name in ("provision.sh", "lib.sh"):
        shutil.copy(DEVICE / name, device / name)
    result = subprocess.run(
        ["bash", str(device / "provision.sh"), *args],
        env=clean_env(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert message in result.stderr.lower()


def test_provision_runs_base_then_included_modules_and_records_revision(tmp_path):
    device = tmp_path / "device"
    for name in ("provision.sh", "lib.sh"):
        (device / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(DEVICE / name, device / name)
    for module in ("base", "bluetooth", "nfc", "wifi"):
        (device / module).mkdir()
        write_executable(device / module / "setup.sh", SETUP_STUB)
    info = {"version": "v1.0.0", "modules": ["wifi", "nfc"], "provision_rev": REV}
    (tmp_path / "build_info.json").write_text(json.dumps(info), encoding="utf-8")
    etc = tmp_path / "etc"
    etc.mkdir()
    log = tmp_path / "setup.log"

    result = subprocess.run(
        [
            "bash",
            str(device / "provision.sh"),
            "--os-upgrade",
            "--hold-wpasupplicant",
            "--i2c-baudrate",
            "400000",
        ],
        env=clean_env(NFC_SKIP_ROOT_CHECK="1", NFC_ETC_DIR=str(etc), STUB_LOG=str(log)),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert log.read_text(encoding="utf-8").splitlines() == [
        "base 1 0 hold 400000 0",
        "nfc 1 0 hold 400000 0",
        "wifi 1 0 hold 400000 0",
    ]
    assert (etc / "provision-rev").read_text(encoding="utf-8") == REV + "\n"


def test_run_detached_rejects_foreign_unit_names():
    result = subprocess.run(
        ["bash", str(RUN_DETACHED), "ssh", "true"],
        env=clean_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "invalid unit name" in result.stderr


def test_run_detached_passes_arguments_verbatim_and_returns_exit_code(tmp_path):
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    write_executable(stubs / "systemd-run", SYSTEMD_RUN_STUB)
    write_executable(stubs / "journalctl", JOURNALCTL_STUB)
    write_executable(stubs / "systemctl", INACTIVE_SYSTEMCTL_STUB)
    env = clean_env(
        PATH=f"{stubs}{os.pathsep}{os.environ.get('PATH', '')}",
        NFC_SKIP_ROOT_CHECK="1",
        NFC_RUN_DIR=str(tmp_path),
        STUB_JOURNAL=str(tmp_path / "journal"),
    )
    command = ["bash", "-c", 'printf "%s|" "$@"; exit 3', "cmd", "a b", "$HOME", "semi;colon"]
    result = subprocess.run(
        ["bash", str(RUN_DETACHED), "nfc-player-test", *command],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 3, result.stdout + result.stderr
    assert "a b|$HOME|semi;colon|" in result.stdout
    assert not (tmp_path / "nfc-player-test.rc").exists()


# --- install-release.sh ------------------------------------------------------


def test_install_release_switch_and_prune(tmp_path):
    dev = FakeDevice(tmp_path)
    seed_old_releases(dev)
    bundle = write_bundle(tmp_path / "bundle.tgz", bundle_members("v1.0.0", ["spotify", "update"]))

    result = dev.run(str(bundle), NFC_HEALTH_SECONDS="1")  # one sleep: exercises the check loop

    assert result.returncode == 0, result.stdout + result.stderr
    current = dev.link("current")
    assert NEW_RELEASE.fullmatch(current), current
    assert dev.link("previous") == OLD_CURRENT
    assert not dev.marker.exists(), "provision-rev unchanged, provisioning must not run"

    # Prune keeps current, previous and the newest other release, and unused venvs go.
    assert dev.releases() == {Path(current).name, Path(OLD_CURRENT).name, Path(OLD_PREVIOUS).name}
    assert {path.name for path in (dev.root / "venvs").iterdir()} == {"aaaaaaaaaaaa"}
    lock12 = hashlib.sha256(LOCK).hexdigest()[:12]
    assert os.readlink(dev.root / current / "venv") == f"../../venvs/{lock12}"
    assert list((dev.root / current / "src/nfc_player/__pycache__").glob("*.pyc"))

    # Units of the included modules with the UID filled in; excluded ones removed.
    assert {path.name for path in dev.units.iterdir()} == {
        "nfc-player.service",
        "nfc-player-config.service",
        "nfc-player-receiver.service",
        "nfc-player-update.service",
        "nfc-player-update.timer",
        "foreign.service",
    }
    receiver = (dev.units / "nfc-player-receiver.service").read_text(encoding="utf-8")
    assert f"user@{UID}.service" in receiver
    assert f"PULSE_SERVER=unix:/run/user/{UID}/pulse/native" in receiver
    assert not [path.name for path in dev.units.iterdir() if "@NFC_UID@" in path.read_text(encoding="utf-8")]
    wrappers = {"nfc-log", "nfc-status", "nfc-restart", "nfc-test"}
    assert {path.name for path in dev.bin.iterdir()} == wrappers | {"nfc-list"}
    assert all(os.access(dev.bin / name, os.X_OK) for name in wrappers)
    assert (dev.profile / "nfc-player.sh").is_file()

    calls = dev.calls()
    assert "daemon-reload" in calls
    assert "disable --now nfc-player-bluetooth.service" in calls
    enable = next(call for call in calls if call.startswith("enable "))
    assert "nfc-player-update.timer" in enable.split()
    assert "nfc-player-update.service" not in enable.split()
    restart = next(call for call in calls if call.startswith("restart "))
    assert set(restart.split()[1:]) == {"nfc-player.service", "nfc-player-receiver.service"}
    assert calls.index("start nfc-player-config.service") < calls.index(restart)
    assert not [call for call in calls if re.match(r"(start|restart)\b.*nfc-player-update", call)]


def test_install_release_rollback_restores_previous(tmp_path):
    dev = FakeDevice(tmp_path)
    seed_old_releases(dev)
    bundle = write_bundle(tmp_path / "bundle.tgz", bundle_members("v1.0.0", ["spotify", "update"]))

    result = dev.run(str(bundle), STUB_FAILED_UNIT="nfc-player.service")

    assert result.returncode == 1, result.stdout + result.stderr
    assert dev.link("current") == OLD_CURRENT
    assert dev.link("previous") == OLD_PREVIOUS
    assert (dev.root / "current").resolve(strict=True).is_dir()
    # The old release's units and wrappers are back, the new release's extras gone.
    assert (dev.units / "nfc-player-bluetooth.service").is_file()
    assert (dev.bin / "nfc-bt").is_file()
    assert not (dev.units / "nfc-player-update.timer").exists()
    # Nothing pruned; the failed release stays for diagnosis.
    releases = dev.releases()
    assert set(OLD_RELEASES) < releases
    assert any(name.endswith("-v1.0.0") for name in releases)
    restarts = [call for call in dev.calls() if call.startswith("restart ")]
    assert len(restarts) == 2
    assert "nfc-player-bluetooth.service" in restarts[-1].split()


def test_install_release_rollback_flag_swaps_current_and_previous(tmp_path):
    dev = FakeDevice(tmp_path)
    seed_old_releases(dev)

    result = dev.run("--rollback")

    assert result.returncode == 0, result.stdout + result.stderr
    assert dev.link("current") == OLD_PREVIOUS
    assert dev.link("previous") == OLD_CURRENT
    assert any(call.startswith("restart ") for call in dev.calls())


def test_install_release_rollback_flag_needs_previous(tmp_path):
    result = FakeDevice(tmp_path).run("--rollback")
    assert result.returncode == 1
    assert "previous" in result.stderr


def test_install_release_runs_provision_when_rev_differs(tmp_path):
    dev = FakeDevice(tmp_path)
    (dev.etc / "provision-rev").write_text("0" * 64 + "\n", encoding="utf-8")
    bundle = write_bundle(tmp_path / "bundle.tgz", bundle_members("v1.0.0", ["spotify"]))

    result = dev.run(str(bundle))

    assert result.returncode == 0, result.stdout + result.stderr
    assert dev.marker.read_text(encoding="utf-8") == "ran\n"
    assert NEW_RELEASE.fullmatch(dev.link("current"))
    assert not (dev.root / "previous").exists()


@pytest.mark.parametrize("broken", ["missing", "bad-version"])
def test_install_release_rejects_bad_build_info(tmp_path, broken):
    dev = FakeDevice(tmp_path)
    members = bundle_members("../evil", ["spotify"])
    if broken == "missing":
        del members["build_info.json"]
    bundle = write_bundle(tmp_path / "bundle.tgz", members)

    result = dev.run(str(bundle))

    assert result.returncode != 0
    assert "build_info.json" in result.stderr
    assert not (dev.root / "current").exists()
    assert dev.releases() == set()
