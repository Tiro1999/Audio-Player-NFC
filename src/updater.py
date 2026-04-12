"""Auto-updater — checks GitHub releases and updates the project on boot.

Flow:
  1. Read local version from version.txt
  2. Ping github.com (skip if offline)
  3. Fetch latest GitHub release tag
  4. Compare semver versions
  5. If newer: download tarball → extract → overwrite src/tools/setup → pip install → restart

Requirements:
  - Public GitHub repo (recommended) OR private repo with a PAT token
  - config.json → update.auto_update = true
  - config.json → update.github_repo = "owner/repo-name"

No external dependencies — uses only Python stdlib (urllib, tarfile, json).
"""

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

from .logger import Logger

logger = Logger(__name__)

_PROJECT_DIR = pathlib.Path(__file__).resolve().parent.parent
_VERSION_FILE = _PROJECT_DIR / "version.txt"

# Files/directories that get replaced during an update
_UPDATE_TARGETS = ["src", "tools", "setup", "requirements.txt", "version.txt"]

# Directories that must NEVER be touched (user data / runtime state)
_PROTECTED = {"venv", "logs", "spotify_cache", "config.json", ".env", "__pycache__"}


# ── Version helpers ───────────────────────────────────────────────────────

def read_local_version():
    """Read current version from version.txt (e.g. 'v0.1.0')."""
    try:
        return _VERSION_FILE.read_text().strip()
    except FileNotFoundError:
        return "v0.0.0"


def _parse_version(v):
    """Parse 'v1.2.3' → (1, 2, 3) for comparison."""
    v = v.lstrip("v").strip()
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


# ── Network helpers ───────────────────────────────────────────────────────

def _github_is_reachable():
    """Quick connectivity check (ping github.com)."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "3", "github.com"],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _github_api_request(url, token=""):
    """Make a GET request to the GitHub API, return parsed JSON or None."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "NFC-SpotiPi-Updater/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError,
            json.JSONDecodeError, OSError) as exc:
        logger.debug("GitHub API request failed (%s): %s", url, exc)
        return None


# ── Release lookup ────────────────────────────────────────────────────────

def _fetch_latest_version(github_repo, token=""):
    """Get the latest release tag from GitHub.

    Tries /releases/latest first (GitHub Releases).
    Falls back to /tags (plain git tags) if no releases exist.
    """
    # Try releases first (preferred — user creates a GitHub Release)
    url = f"https://api.github.com/repos/{github_repo}/releases/latest"
    data = _github_api_request(url, token)
    if data and "tag_name" in data:
        return data["tag_name"]

    # Fallback: plain git tags (sorted by creation date, newest first)
    url = f"https://api.github.com/repos/{github_repo}/tags?per_page=1"
    data = _github_api_request(url, token)
    if data and isinstance(data, list) and len(data) > 0:
        return data[0].get("name", "")

    return None


# ── Download & apply ──────────────────────────────────────────────────────

def _download_tarball(github_repo, tag, token=""):
    """Download the release tarball to a temp file. Returns path or None."""
    url = f"https://github.com/{github_repo}/archive/refs/tags/{tag}.tar.gz"
    headers = {"User-Agent": "NFC-SpotiPi-Updater/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        req = urllib.request.Request(url, headers=headers)
        tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
        with urllib.request.urlopen(req, timeout=120) as resp:
            shutil.copyfileobj(resp, tmp)
        tmp.close()
        size_kb = os.path.getsize(tmp.name) / 1024
        logger.debug("Downloaded %.1f KB → %s", size_kb, tmp.name)
        return tmp.name
    except Exception as exc:
        logger.error("Tarball download failed: %s", exc)
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
        return None


def _apply_tarball(tarball_path):
    """Extract tarball and copy update targets into the project directory.

    Returns True on success, False on failure.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Extract
        try:
            with tarfile.open(tarball_path) as tf:
                tf.extractall(tmpdir)
        except Exception as exc:
            logger.error("Tarball extraction failed: %s", exc)
            return False

        # GitHub tarballs have a single top-level directory
        entries = os.listdir(tmpdir)
        if len(entries) != 1:
            logger.error("Unexpected tarball structure: %s", entries)
            return False

        src_root = pathlib.Path(tmpdir) / entries[0]

        # Copy each update target
        for target in _UPDATE_TARGETS:
            src = src_root / target
            dst = _PROJECT_DIR / target
            if not src.exists():
                logger.debug("Skipping %s (not in release)", target)
                continue
            try:
                if src.is_dir():
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                logger.debug("Updated: %s", target)
            except Exception as exc:
                logger.error("Failed to update %s: %s", target, exc)
                return False

    return True


def _pip_install_if_needed(old_reqs_hash):
    """Run pip install if requirements.txt content changed."""
    reqs = _PROJECT_DIR / "requirements.txt"
    if not reqs.exists():
        return

    new_hash = hashlib.md5(reqs.read_bytes()).hexdigest()
    if new_hash == old_reqs_hash:
        logger.debug("requirements.txt unchanged — skipping pip install")
        return

    logger.info("requirements.txt changed — installing new dependencies …")
    venv_pip = _PROJECT_DIR / "venv" / "bin" / "pip"
    pip_cmd = str(venv_pip) if venv_pip.exists() else "pip3"
    result = subprocess.run(
        [pip_cmd, "install", "-q", "-r", str(reqs)],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        logger.info("Dependencies updated successfully")
    else:
        logger.error("pip install failed: %s", result.stderr.strip())


# ── Public API ────────────────────────────────────────────────────────────

def _normalize_repo(github_repo):
    """Normalize various repo formats to 'owner/name'.

    Accepts:
      - "owner/name"
      - "https://github.com/owner/name"
      - "https://github.com/owner/name.git"
      - "git@github.com:owner/name.git"
    """
    repo = github_repo.strip()
    # SSH format: git@github.com:owner/name.git
    if repo.startswith("git@github.com:"):
        repo = repo.replace("git@github.com:", "")
    # HTTPS format: https://github.com/owner/name[.git]
    for prefix in ("https://github.com/", "http://github.com/"):
        if repo.lower().startswith(prefix):
            repo = repo[len(prefix):]
            break
    repo = repo.rstrip("/").removesuffix(".git")
    return repo


def check_and_update(github_repo, token=""):
    """Check GitHub for a newer release and apply it if available.

    Args:
        github_repo: GitHub repo — accepts "owner/name" or full GitHub URL
        token: Optional GitHub PAT (only needed for private repos)

    Returns:
        True if an update was applied and a restart is needed.
        False if already up-to-date or update was skipped.
    """
    github_repo = _normalize_repo(github_repo)
    if "/" not in github_repo or not github_repo:
        logger.error("Invalid github_repo: '%s' — expected 'owner/repo' format", github_repo)
        return False

    current = read_local_version()
    logger.info("Update check: current version = %s", current)

    # 1. Connectivity check
    if not _github_is_reachable():
        logger.info("GitHub not reachable — skipping update check")
        return False

    # 2. Fetch latest release
    latest_tag = _fetch_latest_version(github_repo, token)
    if not latest_tag:
        logger.info("Could not determine latest version — skipping")
        return False

    logger.info("Update check: latest release  = %s", latest_tag)

    # 3. Compare versions
    if _parse_version(latest_tag) <= _parse_version(current):
        logger.info("Already up to date ✓")
        return False

    logger.info("Update available: %s → %s", current, latest_tag)

    # 4. Save current requirements hash
    reqs = _PROJECT_DIR / "requirements.txt"
    old_reqs_hash = hashlib.md5(reqs.read_bytes()).hexdigest() if reqs.exists() else ""

    # 5. Download
    logger.info("Downloading %s …", latest_tag)
    tarball = _download_tarball(github_repo, latest_tag, token)
    if not tarball:
        return False

    # 6. Apply
    try:
        logger.info("Applying update …")
        if not _apply_tarball(tarball):
            logger.error("Update failed — keeping current version")
            return False

        # 7. Install new dependencies if needed
        _pip_install_if_needed(old_reqs_hash)

        logger.info("══════════════════════════════════════════")
        logger.info("  ✅ Updated to %s", latest_tag)
        logger.info("══════════════════════════════════════════")
        return True
    finally:
        try:
            os.unlink(tarball)
        except OSError:
            pass
