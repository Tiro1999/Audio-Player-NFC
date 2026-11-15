"""Auto-update from GitHub: installs the latest release when it is newer than the running one.

Runs as root (nfc-player-update.service). The source comes from api.github.com only; the
downloaded release builds its own bundle, and install-release.sh installs it with health
check and rollback.
"""

import argparse
import http.client
import json
import logging
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zlib
from pathlib import Path

from nfc_player.core.build_info import load_build_info
from nfc_player.core.config import ConfigError, load_config
from nfc_player.core.log import setup_logging
from nfc_player.core.paths import DEVICE_CONFIG, UPDATE_TOKEN
from nfc_player.core.process import Result, Runner, run
from nfc_player.core.validate import normalize_repo

log = logging.getLogger(__name__)

TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")
USER_AGENT = "nfc-player-updater"
API_TIMEOUT = 15  # s per API request
DOWNLOAD_TIMEOUT = 120  # s
INSTALL_TIMEOUT = 1800  # s: venv, provisioning and health check on a Pi Zero 2 W

_TOKEN = re.compile(r"[!-~]+")  # as in core.config: printable ASCII without spaces
# What a broken tarball raises while it is unpacked.
_TARBALL_ERRORS = (OSError, EOFError, ValueError, tarfile.TarError, zlib.error)


def parse_version(v: str) -> tuple[int, int, int]:
    """'v1.2.3' → (1, 2, 3). Missing or non-numeric parts count as 0; parts after the third are ignored."""
    parts = [_number(part) for part in v.lstrip("v").strip().split(".")]
    major, minor, patch = (parts + [0, 0, 0])[:3]
    return major, minor, patch


def _number(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        return 0


def _is_tag(value: object) -> bool:
    """True for a tag like v1.2.3 in ASCII digits (\\d alone also matches other scripts)."""
    return isinstance(value, str) and value.isascii() and TAG_RE.fullmatch(value) is not None


# --- GitHub API ---


def _request(path: str, token: str | None) -> urllib.request.Request:
    """GET request to api.github.com, the only host the updater asks."""
    request = urllib.request.Request(
        f"https://api.github.com/{path}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT},
    )
    if token:
        if not _TOKEN.fullmatch(token):
            # Checked here: http.client would quote a rejected header value, token included.
            raise ValueError("the update token must be printable ASCII without spaces")
        # Unredirected: the tarball redirect to codeload.github.com must not get the token.
        request.add_unredirected_header("Authorization", f"Bearer {token}")
    return request


def _repo_path(repo: str) -> str:
    return f"repos/{normalize_repo(repo)}"


def _get_json(path: str, token: str | None, urlopen) -> object:
    with urlopen(_request(path, token), timeout=API_TIMEOUT) as response:
        return json.load(response)


# NAMING-CHECK: "release" means a GitHub release here; the glossary's release is an installed version.
def latest_release_tag(repo: str, token: str | None, *, urlopen=urllib.request.urlopen) -> str | None:
    """Tag of the latest GitHub release, else the highest tag like v1.2.3; None if there is neither.

    A repo without releases (404) falls back to its tags; other HTTP and network errors are raised.
    """
    base = _repo_path(repo)
    try:
        release = _get_json(f"{base}/releases/latest", token, urlopen)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        release = {}
    tag = release.get("tag_name") if isinstance(release, dict) else None
    if _is_tag(tag):
        return tag
    tags = _get_json(f"{base}/tags?per_page=100", token, urlopen)
    entries = tags if isinstance(tags, list) else []
    names = [entry.get("name") for entry in entries if isinstance(entry, dict)]
    return max(filter(_is_tag, names), key=parse_version, default=None)


def download_tarball(
    repo: str, tag: str, token: str | None, dest: Path, *, urlopen=urllib.request.urlopen
) -> Path:
    """Save the source tarball of `tag` from the GitHub API to `dest`."""
    if not _is_tag(tag):
        raise ValueError("a release tag must look like v1.2.3")
    request = _request(f"{_repo_path(repo)}/tarball/{tag}", token)
    with urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response, dest.open("wb") as file:
        shutil.copyfileobj(response, file)
    return dest


def extract_source(tarball: Path, dest: Path) -> Path:
    """Unpack a source tarball into the new directory `dest`; returns its only top-level directory.

    The "data" filter refuses absolute paths, "..", links leaving `dest` and device files.
    """
    dest.mkdir(parents=True)
    with tarfile.open(tarball) as archive:
        archive.extractall(dest, filter="data")
    entries = list(dest.iterdir())
    if len(entries) != 1 or not entries[0].is_dir():
        raise ValueError("the source tarball must hold exactly one top-level directory")
    return entries[0]


# --- Update ---


def check_and_update(
    repo: str,
    token: str | None,
    current_version: str,
    workdir: Path,
    *,
    urlopen=urllib.request.urlopen,
    runner: Runner = run,
) -> str:
    """Install the latest GitHub release of `repo` if it is newer than `current_version`.

    `workdir` is an empty directory for the download and the bundle.
    Returns "up-to-date", "offline" (GitHub not reachable), "updated" or "failed".
    """
    log.info("Looking for a release newer than %s in %s", current_version, repo)
    try:
        tag = latest_release_tag(repo, token, urlopen=urlopen)
    except (urllib.error.HTTPError, ValueError) as exc:  # their messages hold no token
        log.error("Release lookup failed: %s", exc)
        return "failed"
    except (OSError, http.client.HTTPException) as exc:
        log.info("GitHub not reachable, no update check: %s", exc)
        return "offline"
    if tag is None:
        log.warning("%s has no release or tag like v1.2.3", repo)
        return "up-to-date"
    if parse_version(tag) <= parse_version(current_version):
        log.info("%s is up to date (latest on GitHub: %s)", current_version, tag)
        return "up-to-date"

    log.info("Updating %s to %s", current_version, tag)
    try:
        tarball = download_tarball(repo, tag, token, workdir / "source.tar.gz", urlopen=urlopen)
    except (OSError, http.client.HTTPException) as exc:
        log.error("Download of %s failed: %s", tag, exc)
        return "failed"
    try:
        source = extract_source(tarball, workdir / "source")
    except _TARBALL_ERRORS as exc:
        log.error("Source tarball of %s is unusable: %s", tag, exc)
        return "failed"

    log.info("Building the bundle of %s", tag)
    bundle_py = source / "deploy/bundle.py"
    build = runner(
        [sys.executable, str(bundle_py), "--out", str(workdir), "--maturity", "release", "--version", tag]
    )
    if not _succeeded(build, "bundle build"):
        return "failed"
    log.info("Installing %s; install-release.sh rolls back if it is unhealthy", tag)
    bundle = workdir / f"nfc-player-{tag}.tgz"  # the name deploy/bundle.py gives it
    install_sh = source / "deploy/device/install-release.sh"
    install = runner(["bash", str(install_sh), str(bundle)], timeout=INSTALL_TIMEOUT)
    if not _succeeded(install, "install"):
        return "failed"
    log.info("Updated to %s", tag)
    return "updated"


def _succeeded(result: Result, step: str) -> bool:
    """On failure log the exit code and the end of the step's output (the steps print no secrets)."""
    if not result.ok:
        tail = (result.stdout.splitlines() + result.stderr.splitlines())[-20:]
        log.error("The %s failed (exit %d):\n%s", step, result.returncode, "\n".join(tail))
    return result.ok


def _read_token(path: Path) -> str | None:
    """The stored GitHub token or None; _request validates it before use."""
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip() or None
    except FileNotFoundError:
        return None


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="Install the latest GitHub release if it is newer.").parse_args(argv)
    build = load_build_info()
    setup_logging(build.maturity)
    try:
        cfg = load_config(DEVICE_CONFIG)
    except FileNotFoundError:
        log.info("No device config yet: auto-update is off")
        return 0
    except ConfigError as exc:
        log.warning("Device config unusable, no update check: %s", exc)
        return 0
    if not cfg.auto_update or not cfg.github_repo:
        log.info("Auto-update is off")
        return 0
    with tempfile.TemporaryDirectory(prefix="nfc-player-update-") as workdir:
        status = check_and_update(cfg.github_repo, _read_token(UPDATE_TOKEN), build.version, Path(workdir))
    return 1 if status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
