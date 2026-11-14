"""Tests for nfc_player.core.build_info."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from nfc_player.core.build_info import SOURCE_BUILD, BuildInfo, load_build_info, parse_build_info

ALL_MODULES = ("nfc", "spotify", "wifi", "bluetooth", "update")
PACKAGE_DIR = Path(__file__).resolve().parents[2] / "src" / "nfc_player"


def test_load_build_info_missing_returns_source_build(tmp_path):
    build = load_build_info(tmp_path / "build_info.json")
    assert build == SOURCE_BUILD
    assert build.version == "0.0.0+source"
    assert build.maturity == "dev"
    assert all(build.has(module) for module in ALL_MODULES)


def test_load_build_info_reads_release_file(tmp_path):
    path = tmp_path / "build_info.json"
    data = {
        "version": "v1.2.3",
        "maturity": "release",
        "modules": ["nfc", "spotify"],
        "built": "2026-11-13T10:00:00Z",
        "provision_rev": "ab" * 32,
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_build_info(path) == BuildInfo(
        "v1.2.3", "release", ("nfc", "spotify"), "2026-11-13T10:00:00Z", "ab" * 32
    )


def test_load_build_info_default_is_release_root(tmp_path):
    # Release layout: build_info.json sits at the release root, next to src/nfc_player/.
    shutil.copytree(
        PACKAGE_DIR, tmp_path / "src" / "nfc_player", ignore=shutil.ignore_patterns("__pycache__")
    )
    data = {"version": "v9.9.9", "maturity": "release", "modules": []}
    (tmp_path / "build_info.json").write_text(json.dumps(data), encoding="utf-8")
    code = "from nfc_player.core.build_info import load_build_info; print(load_build_info().version)"
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env={"PYTHONPATH": str(tmp_path / "src")},
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == "v9.9.9"


def test_load_build_info_corrupt_file_raises(tmp_path):
    path = tmp_path / "build_info.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError):
        load_build_info(path)


def test_parse_build_info_rejects_unknown_module():
    with pytest.raises(ValueError):
        parse_build_info({"version": "v1.0.0", "maturity": "release", "modules": ["nfc", "teleport"]})


@pytest.mark.parametrize(
    "data",
    [
        {"maturity": "release", "modules": []},
        {"version": "", "maturity": "release", "modules": []},
        {"version": "v1.0.0", "maturity": "beta", "modules": []},
        {"version": "v1.0.0", "modules": []},
        {"version": "v1.0.0", "maturity": "release"},
        {"version": "v1.0.0", "maturity": "release", "modules": "nfc"},
        {"version": "v1.0.0", "maturity": "release", "modules": [], "built": 5},
        ["v1.0.0"],
    ],
)
def test_parse_build_info_rejects_invalid(data):
    with pytest.raises(ValueError):
        parse_build_info(data)


def test_buildinfo_has():
    build = BuildInfo("v1.0.0", "release", ("nfc", "wifi"))
    assert build.has("wifi")
    assert not build.has("spotify")
