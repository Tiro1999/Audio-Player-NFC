"""Build info of the running release (build_info.json at the release root).

A source checkout has no build_info.json and runs as SOURCE_BUILD.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MATURITIES = ("dev", "experimental", "release")
MODULES = ("nfc", "spotify", "wifi", "bluetooth", "update")


@dataclass(frozen=True)
class BuildInfo:
    version: str
    maturity: str
    modules: tuple[str, ...]
    built: str = ""
    provision_rev: str = ""

    def has(self, module: str) -> bool:
        """True if the optional `module` (see MODULES) is part of this build."""
        return module in self.modules


SOURCE_BUILD = BuildInfo("0.0.0+source", "dev", MODULES)


def parse_build_info(data: Mapping[str, Any]) -> BuildInfo:
    """Validate the content of build_info.json; ValueError if it is unusable."""
    if not isinstance(data, Mapping):
        raise ValueError("build info must be a JSON object")
    version = data.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("build info has no version")
    maturity = data.get("maturity")
    if maturity not in MATURITIES:
        raise ValueError(f"unknown maturity: {maturity!r}")
    modules = data.get("modules")
    if not isinstance(modules, list | tuple) or any(module not in MODULES for module in modules):
        raise ValueError(f"unknown modules: {modules!r}")
    built, provision_rev = data.get("built", ""), data.get("provision_rev", "")
    if not isinstance(built, str) or not isinstance(provision_rev, str):
        raise ValueError("built and provision_rev must be text")
    return BuildInfo(version, maturity, tuple(modules), built, provision_rev)


def load_build_info(path: Path | None = None) -> BuildInfo:
    """Read build_info.json at the release root, next to src/. Missing file → SOURCE_BUILD."""
    if path is None:
        path = Path(__file__).resolve().parents[3] / "build_info.json"
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return SOURCE_BUILD
    return parse_build_info(json.loads(text))
