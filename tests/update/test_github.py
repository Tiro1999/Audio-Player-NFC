"""Tests for nfc_player.update.github. No network: urlopen and the runner are fakes."""

import hashlib
import io
import json
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY

import pytest

from nfc_player.core.build_info import BuildInfo
from nfc_player.core.process import Result
from nfc_player.update import github
from nfc_player.update.github import (
    check_and_update,
    download_tarball,
    extract_source,
    latest_release_tag,
    parse_version,
)

REPO = "owner/repo"
API = "https://api.github.com/repos/owner/repo"
RELEASE_URL = f"{API}/releases/latest"
TAGS_URL = f"{API}/tags?per_page=100"
TOKEN = "ghp_Secret123"
TOP = "owner-repo-1a2b3c4"  # GitHub names the top-level directory owner-repo-<commit>


class FakeGitHub:
    """urlopen fake: answers each URL with JSON, bytes or an exception and records the requests."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []
        self.timeouts = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        self.timeouts.append(timeout)
        answer = self.routes[request.full_url]
        if isinstance(answer, BaseException):
            raise answer
        return io.BytesIO(answer if isinstance(answer, bytes) else json.dumps(answer).encode())

    @property
    def urls(self):
        return [request.full_url for request in self.requests]


class FakeRunner:
    """Runner fake: returns the given results (or exit codes) in order and records the calls."""

    def __init__(self, *results):
        self.results = [Result(r, "", "") if isinstance(r, int) else r for r in results]
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((list(args), kwargs))
        return self.results.pop(0)


def not_found(url=RELEASE_URL):
    return urllib.error.HTTPError(url, 404, "Not Found", None, None)


def make_tarball(path, members):
    """Write a .tar.gz; `members` maps a name to file content, or to None for a directory."""
    with tarfile.open(path, "w:gz") as archive:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            if content is None:
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                archive.addfile(info)
            else:
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
    return path


def source_tarball(tmp_path):
    """Bytes of a GitHub-style source tarball: one top-level directory with the deploy scripts."""
    members = {
        f"{TOP}/": None,
        f"{TOP}/deploy/bundle.py": b"# bundle builder\n",
        f"{TOP}/deploy/device/install-release.sh": b"# installer\n",
    }
    return make_tarball(tmp_path / "upstream.tar.gz", members).read_bytes()


def release_api(tmp_path, tag="v1.3.0"):
    return FakeGitHub({RELEASE_URL: {"tag_name": tag}, f"{API}/tarball/{tag}": source_tarball(tmp_path)})


@pytest.fixture
def workdir(tmp_path):
    path = tmp_path / "work"
    path.mkdir()
    return path


# --- Versions (ported from the old updater) ---


class TestParseVersion:
    """Test semver parsing."""

    def test_standard(self):
        assert parse_version("v1.2.3") == (1, 2, 3)

    def test_without_v_prefix(self):
        assert parse_version("1.2.3") == (1, 2, 3)

    def test_two_parts(self):
        assert parse_version("v1.2") == (1, 2, 0)

    def test_single_part(self):
        assert parse_version("v3") == (3, 0, 0)

    def test_empty_string(self):
        assert parse_version("") == (0, 0, 0)

    def test_non_numeric_parts(self):
        assert parse_version("v1.beta.3") == (1, 0, 3)

    def test_extra_parts_ignored(self):
        assert parse_version("v1.2.3.4") == (1, 2, 3)

    def test_whitespace(self):
        assert parse_version("  v0.1.0  ") == (0, 1, 0)


class TestVersionComparison:
    """Test that version tuples compare correctly."""

    def test_newer_major(self):
        assert parse_version("v2.0.0") > parse_version("v1.9.9")

    def test_newer_minor(self):
        assert parse_version("v1.3.0") > parse_version("v1.2.9")

    def test_newer_patch(self):
        assert parse_version("v1.2.4") > parse_version("v1.2.3")

    def test_equal(self):
        assert parse_version("v1.0.0") == parse_version("v1.0.0")

    def test_equal_with_and_without_prefix(self):
        assert parse_version("v1.0.0") == parse_version("1.0.0")

    def test_older(self):
        assert parse_version("v0.1.0") < parse_version("v0.2.0")

    def test_initial_vs_zero(self):
        assert parse_version("v0.1.0") > parse_version("v0.0.0")


# --- Release lookup ---


def test_latest_release_tag_prefers_valid_release():
    github_api = FakeGitHub({RELEASE_URL: {"tag_name": "v1.3.0"}})
    assert latest_release_tag(REPO, None, urlopen=github_api) == "v1.3.0"
    assert github_api.urls == [RELEASE_URL]


def test_latest_release_tag_rejects_bad_tag():
    github_api = FakeGitHub({RELEASE_URL: {"tag_name": "v1.0.0;rm"}, TAGS_URL: [{"name": "v0.9.0"}]})
    assert latest_release_tag(REPO, None, urlopen=github_api) == "v0.9.0"
    assert github_api.urls == [RELEASE_URL, TAGS_URL]


def test_latest_from_tags_picks_highest():
    tags = [{"name": name} for name in ["v0.9.0", "v0.10.0", "v0.2.0"]]
    github_api = FakeGitHub({RELEASE_URL: not_found(), TAGS_URL: tags})
    assert latest_release_tag(REPO, None, urlopen=github_api) == "v0.10.0"


def test_latest_from_tags_ignores_invalid_tags():
    invalid = ["v9.0.0\n", "v٩.0.0", "v9.0", "v9.0.0-rc1", "nightly", None, 9]
    tags = [{"name": name} for name in invalid] + ["v8.0.0", {}, {"name": "v0.1.0"}]
    github_api = FakeGitHub({RELEASE_URL: not_found(), TAGS_URL: tags})
    assert latest_release_tag(REPO, None, urlopen=github_api) == "v0.1.0"


def test_latest_release_tag_none_without_tags():
    github_api = FakeGitHub({RELEASE_URL: not_found(), TAGS_URL: []})
    assert latest_release_tag(REPO, None, urlopen=github_api) is None


def test_latest_release_tag_accepts_github_url():
    github_api = FakeGitHub({RELEASE_URL: {"tag_name": "v1.0.0"}})
    assert latest_release_tag("https://github.com/owner/repo.git", None, urlopen=github_api) == "v1.0.0"
    assert github_api.urls == [RELEASE_URL]


@pytest.mark.parametrize("repo", ["owner", "owner/..", "a/b/c", "https://evil.example/owner/repo"])
def test_latest_release_tag_rejects_invalid_repo(repo):
    github_api = FakeGitHub({})
    with pytest.raises(ValueError):
        latest_release_tag(repo, None, urlopen=github_api)
    assert github_api.requests == []


# --- Headers and token ---


@pytest.mark.parametrize("token", [TOKEN, None])
def test_token_header_only_when_set(token):
    github_api = FakeGitHub({RELEASE_URL: {"tag_name": "v1.0.0"}})
    latest_release_tag(REPO, token, urlopen=github_api)
    [request] = github_api.requests
    assert request.get_header("Accept") == "application/vnd.github+json"
    assert request.get_header("User-agent") == "nfc-player-updater"
    assert request.get_header("Authorization") == (f"Bearer {TOKEN}" if token else None)


def test_token_not_forwarded_on_redirect(tmp_path):
    github_api = FakeGitHub({f"{API}/tarball/v1.3.0": b"tarball"})
    download_tarball(REPO, "v1.3.0", TOKEN, tmp_path / "source.tar.gz", urlopen=github_api)
    [request] = github_api.requests
    assert request.get_header("Authorization") == f"Bearer {TOKEN}"
    # The API redirects the download to codeload.github.com; that request must not carry the token.
    codeload = "https://codeload.github.com/owner/repo/legacy.tar.gz/refs/tags/v1.3.0"
    redirected = urllib.request.HTTPRedirectHandler().redirect_request(
        request, None, 302, "Found", {}, codeload
    )
    assert not redirected.has_header("Authorization")


@pytest.mark.parametrize("token", ["ghp_one ghp_two", "ghp_one\r\nX-Evil: 1", "ghp_ä"])
def test_check_and_update_refuses_invalid_token(workdir, caplog, token):
    caplog.set_level(1)
    github_api = FakeGitHub({})
    runner = FakeRunner()
    assert check_and_update(REPO, token, "v1.2.0", workdir, urlopen=github_api, runner=runner) == "failed"
    assert github_api.requests == []
    assert token not in caplog.text


# --- Download and extraction ---


def test_download_tarball_from_api(tmp_path):
    github_api = FakeGitHub({f"{API}/tarball/v1.3.0": b"tarball bytes"})
    dest = tmp_path / "source.tar.gz"
    assert download_tarball(REPO, "v1.3.0", None, dest, urlopen=github_api) == dest
    assert dest.read_bytes() == b"tarball bytes"
    assert github_api.urls == ["https://api.github.com/repos/owner/repo/tarball/v1.3.0"]
    assert github_api.timeouts == [120]


@pytest.mark.parametrize("tag", ["v1.0.0;rm", "v1.0.0\n", "../v1.0.0", "main"])
def test_download_tarball_rejects_invalid_tag(tmp_path, tag):
    github_api = FakeGitHub({})
    with pytest.raises(ValueError):
        download_tarball(REPO, tag, None, tmp_path / "source.tar.gz", urlopen=github_api)
    assert github_api.requests == []


def test_extract_source_returns_top_dir(tmp_path):
    tarball = make_tarball(tmp_path / "source.tar.gz", {f"{TOP}/": None, f"{TOP}/deploy/bundle.py": b"x\n"})
    top = extract_source(tarball, tmp_path / "dest")
    assert top == tmp_path / "dest" / TOP
    assert (top / "deploy" / "bundle.py").read_bytes() == b"x\n"


@pytest.mark.parametrize("evil", ["../evil", f"{TOP}/../../evil"])
def test_extract_source_blocks_path_traversal(tmp_path, evil):
    tarball = make_tarball(tmp_path / "source.tar.gz", {f"{TOP}/README": b"ok\n", evil: b"pwned\n"})
    with pytest.raises(tarfile.OutsideDestinationError):
        extract_source(tarball, tmp_path / "dest")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["dest", "source.tar.gz"]


@pytest.mark.parametrize(
    "members",
    [
        pytest.param({"a/x": b"", "b/y": b""}, id="two-dirs"),
        pytest.param({"README": b"text\n"}, id="file-only"),
        pytest.param({}, id="empty"),
    ],
)
def test_extract_source_requires_single_top_dir(tmp_path, members):
    tarball = make_tarball(tmp_path / "source.tar.gz", members)
    with pytest.raises(ValueError):
        extract_source(tarball, tmp_path / "dest")


# --- check_and_update ---


@pytest.mark.parametrize("current", ["v1.2.0", "v1.3.0"])
def test_check_and_update_up_to_date(workdir, current):
    github_api = FakeGitHub({RELEASE_URL: {"tag_name": "v1.2.0"}})
    runner = FakeRunner()
    assert check_and_update(REPO, None, current, workdir, urlopen=github_api, runner=runner) == "up-to-date"
    assert runner.calls == []
    assert github_api.urls == [RELEASE_URL]


def test_check_and_update_without_any_tag_is_up_to_date(workdir):
    github_api = FakeGitHub({RELEASE_URL: not_found(), TAGS_URL: []})
    runner = FakeRunner()
    assert check_and_update(REPO, None, "v1.2.0", workdir, urlopen=github_api, runner=runner) == "up-to-date"
    assert runner.calls == []


def test_check_and_update_runs_bundle_then_installer(tmp_path, workdir, caplog):
    caplog.set_level(1)
    runner = FakeRunner(0, 0)
    github_api = release_api(tmp_path)
    assert check_and_update(REPO, TOKEN, "v1.2.0", workdir, urlopen=github_api, runner=runner) == "updated"
    assert github_api.urls == [RELEASE_URL, f"{API}/tarball/v1.3.0"]
    (bundle_args, _), (install_args, install_kwargs) = runner.calls
    out = str(workdir)
    assert bundle_args == [sys.executable, ANY, "--out", out, "--maturity", "release", "--version", "v1.3.0"]
    assert install_args == ["bash", ANY, str(workdir / "nfc-player-v1.3.0.tgz")]
    assert install_kwargs == {"timeout": 1800}
    # Both scripts are the ones of the downloaded release.
    bundle_py, install_sh = Path(bundle_args[1]), Path(install_args[1])
    assert bundle_py.is_relative_to(workdir) and install_sh.is_relative_to(workdir)
    assert bundle_py.read_bytes() == b"# bundle builder\n"
    assert install_sh.read_bytes() == b"# installer\n"
    assert TOKEN not in caplog.text


def test_check_and_update_bundle_failure_skips_installer(tmp_path, workdir):
    runner = FakeRunner(1)
    github_api = release_api(tmp_path)
    assert check_and_update(REPO, None, "v1.2.0", workdir, urlopen=github_api, runner=runner) == "failed"
    assert len(runner.calls) == 1


def test_check_and_update_installer_failure_is_failed(tmp_path, workdir, caplog):
    rolled_back = Result(
        1, "Installing release x\n", "release x failed its health check and was rolled back\n"
    )
    runner = FakeRunner(0, rolled_back)
    github_api = release_api(tmp_path)
    assert check_and_update(REPO, None, "v1.2.0", workdir, urlopen=github_api, runner=runner) == "failed"
    assert len(runner.calls) == 2
    assert "was rolled back" in caplog.text


@pytest.mark.parametrize(
    "error", [urllib.error.URLError("Network is unreachable"), TimeoutError("timed out")]
)
def test_check_and_update_offline_on_urlerror(workdir, error):
    github_api = FakeGitHub({RELEASE_URL: error})
    runner = FakeRunner()
    assert check_and_update(REPO, None, "v1.2.0", workdir, urlopen=github_api, runner=runner) == "offline"
    assert runner.calls == []


def test_check_and_update_http_error_is_failed(workdir, caplog):
    caplog.set_level(1)
    github_api = FakeGitHub(
        {RELEASE_URL: urllib.error.HTTPError(RELEASE_URL, 401, "Unauthorized", None, None)}
    )
    runner = FakeRunner()
    assert check_and_update(REPO, TOKEN, "v1.2.0", workdir, urlopen=github_api, runner=runner) == "failed"
    assert runner.calls == []
    assert TOKEN not in caplog.text


def test_check_and_update_download_error_is_failed(workdir):
    tarball_url = f"{API}/tarball/v1.3.0"
    github_api = FakeGitHub({RELEASE_URL: {"tag_name": "v1.3.0"}, tarball_url: ConnectionResetError("reset")})
    runner = FakeRunner()
    assert check_and_update(REPO, None, "v1.2.0", workdir, urlopen=github_api, runner=runner) == "failed"
    assert runner.calls == []


def truncated_tarball(tmp_path):
    payload = hashlib.shake_256(b"nfc-player").digest(70_000)  # incompressible: the cut hits the data
    return make_tarball(tmp_path / "big.tar.gz", {f"{TOP}/blob": payload}).read_bytes()[:20_000]


def tarball_of(members):
    """Builder for the bytes of a tarball with `members`, written to tmp_path."""
    return lambda tmp_path: make_tarball(tmp_path / "broken.tar.gz", members).read_bytes()


@pytest.mark.parametrize(
    "tarball",
    [
        pytest.param(lambda tmp_path: b"not a tarball", id="garbage"),
        pytest.param(truncated_tarball, id="truncated"),
        pytest.param(tarball_of({"a/x": b"", "b/y": b""}), id="two-dirs"),
        pytest.param(tarball_of({"../evil": b""}), id="traversal"),
    ],
)
def test_check_and_update_unusable_tarball_is_failed(tmp_path, workdir, tarball):
    github_api = FakeGitHub({RELEASE_URL: {"tag_name": "v1.3.0"}, f"{API}/tarball/v1.3.0": tarball(tmp_path)})
    runner = FakeRunner()
    assert check_and_update(REPO, None, "v1.2.0", workdir, urlopen=github_api, runner=runner) == "failed"
    assert runner.calls == []
    assert not (workdir / "evil").exists()


# --- main ---


class FakeCheck:
    """Stands in for check_and_update in main(); records its arguments."""

    def __init__(self):
        self.status = "up-to-date"
        self.calls = []

    def __call__(self, repo, token, current_version, workdir):
        assert workdir.is_dir()
        self.calls.append((repo, token, current_version, workdir))
        return self.status


@pytest.fixture
def device(tmp_path, monkeypatch):
    """main() with its device files in tmp_path, build v1.2.0 and a recording check_and_update."""
    dev = SimpleNamespace(
        config=tmp_path / "config.json", token=tmp_path / "update-token", check=FakeCheck(), maturities=[]
    )
    monkeypatch.setattr(github, "DEVICE_CONFIG", dev.config)
    monkeypatch.setattr(github, "UPDATE_TOKEN", dev.token)
    monkeypatch.setattr(github, "load_build_info", lambda: BuildInfo("v1.2.0", "release", ("update",)))
    monkeypatch.setattr(github, "setup_logging", dev.maturities.append)
    monkeypatch.setattr(github, "check_and_update", dev.check)
    return dev


def write_update_config(path, update):
    path.write_text(json.dumps({"update": update}), encoding="utf-8")


ENABLED = {"auto_update": True, "github_repo": REPO}


@pytest.mark.parametrize(
    "update",
    [
        {"auto_update": False, "github_repo": REPO},
        {"auto_update": True, "github_repo": ""},
        {"auto_update": True},
    ],
)
def test_main_disabled_returns_0(device, update):
    write_update_config(device.config, update)
    assert github.main([]) == 0
    assert device.check.calls == []


def test_main_without_device_config_returns_0(device):
    assert github.main([]) == 0
    assert device.check.calls == []


def test_main_invalid_device_config_returns_0(device):
    device.config.write_text("{not json", encoding="utf-8")
    assert github.main([]) == 0
    assert device.check.calls == []


@pytest.mark.parametrize(
    ("status", "code"), [("up-to-date", 0), ("offline", 0), ("updated", 0), ("failed", 1)]
)
def test_main_exit_code(device, status, code):
    write_update_config(device.config, ENABLED)
    device.check.status = status
    assert github.main([]) == code
    [(repo, token, current_version, workdir)] = device.check.calls
    assert (repo, token, current_version) == (REPO, None, "v1.2.0")
    assert not workdir.exists()  # the temporary workdir is gone
    assert device.maturities == ["release"]


@pytest.mark.parametrize(("content", "expected"), [(f"  {TOKEN}\r\n", TOKEN), ("", None), (" \n", None)])
def test_main_reads_token_file(device, content, expected):
    write_update_config(device.config, ENABLED)
    device.token.write_text(content, encoding="utf-8")
    assert github.main([]) == 0
    assert device.check.calls[0][1] == expected
