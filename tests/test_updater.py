"""Tests for src/updater.py – version parsing and comparison logic."""

import pytest
from src.updater import _parse_version, _normalize_repo, read_local_version


class TestParseVersion:
    """Test semver parsing."""

    def test_standard(self):
        assert _parse_version("v1.2.3") == (1, 2, 3)

    def test_without_v_prefix(self):
        assert _parse_version("1.2.3") == (1, 2, 3)

    def test_two_parts(self):
        assert _parse_version("v1.2") == (1, 2, 0)

    def test_single_part(self):
        assert _parse_version("v3") == (3, 0, 0)

    def test_empty_string(self):
        assert _parse_version("") == (0, 0, 0)

    def test_non_numeric_parts(self):
        assert _parse_version("v1.beta.3") == (1, 0, 3)

    def test_extra_parts_ignored(self):
        assert _parse_version("v1.2.3.4") == (1, 2, 3)

    def test_whitespace(self):
        assert _parse_version("  v0.1.0  ") == (0, 1, 0)


class TestVersionComparison:
    """Test that version tuples compare correctly."""

    def test_newer_major(self):
        assert _parse_version("v2.0.0") > _parse_version("v1.9.9")

    def test_newer_minor(self):
        assert _parse_version("v1.3.0") > _parse_version("v1.2.9")

    def test_newer_patch(self):
        assert _parse_version("v1.2.4") > _parse_version("v1.2.3")

    def test_equal(self):
        assert _parse_version("v1.0.0") == _parse_version("v1.0.0")

    def test_equal_with_and_without_prefix(self):
        assert _parse_version("v1.0.0") == _parse_version("1.0.0")

    def test_older(self):
        assert _parse_version("v0.1.0") < _parse_version("v0.2.0")

    def test_initial_vs_zero(self):
        assert _parse_version("v0.1.0") > _parse_version("v0.0.0")


class TestNormalizeRepo:
    """Test github_repo URL normalization."""

    def test_owner_repo(self):
        assert _normalize_repo("Tiro1999/Audio-Player-NFC") == "Tiro1999/Audio-Player-NFC"

    def test_https_url(self):
        assert _normalize_repo("https://github.com/Tiro1999/Audio-Player-NFC") == "Tiro1999/Audio-Player-NFC"

    def test_https_url_with_git(self):
        assert _normalize_repo("https://github.com/Tiro1999/Audio-Player-NFC.git") == "Tiro1999/Audio-Player-NFC"

    def test_https_url_trailing_slash(self):
        assert _normalize_repo("https://github.com/Tiro1999/Audio-Player-NFC/") == "Tiro1999/Audio-Player-NFC"

    def test_ssh_url(self):
        assert _normalize_repo("git@github.com:Tiro1999/Audio-Player-NFC.git") == "Tiro1999/Audio-Player-NFC"

    def test_whitespace(self):
        assert _normalize_repo("  Tiro1999/Audio-Player-NFC  ") == "Tiro1999/Audio-Player-NFC"

    def test_http_url(self):
        assert _normalize_repo("http://github.com/Tiro1999/Audio-Player-NFC") == "Tiro1999/Audio-Player-NFC"
