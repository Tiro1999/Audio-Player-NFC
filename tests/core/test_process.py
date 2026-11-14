"""Tests for nfc_player.core.process."""

import sys
import time

import pytest

from nfc_player.core.log import TRACE
from nfc_player.core.process import Result, run

PY = sys.executable


def test_run_captures_output_and_returncode():
    result = run([PY, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"])
    assert result == Result(3, "out\n", "err\n")
    assert not result.ok


def test_result_ok_only_for_zero():
    assert Result(0, "", "").ok
    assert not Result(1, "", "").ok


def test_run_sends_input_as_utf8():
    code = "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read().upper())"
    assert run([PY, "-c", code], input="café").stdout == "CAFé"


def test_run_replaces_invalid_utf8_output():
    assert run([PY, "-c", "import sys; sys.stdout.buffer.write(b'a\\xffb')"]).stdout == "a�b"


def test_run_without_input_uses_dev_null():
    result = run([PY, "-c", "import os; print(os.readlink('/proc/self/fd/0'))"])
    assert result.stdout == "/dev/null\n"


def test_run_env_adds_to_current_environment(monkeypatch):
    monkeypatch.setenv("NFC_TEST_BASE", "base")
    code = "import os; print(os.environ['NFC_TEST_BASE'], os.environ['NFC_TEST_EXTRA'])"
    assert run([PY, "-c", code], env={"NFC_TEST_EXTRA": "extra"}).stdout == "base extra\n"


def test_run_timeout_returns_124():
    start = time.monotonic()
    result = run(["sleep", "5"], timeout=0.2)
    assert result.returncode == 124
    assert not result.ok
    assert time.monotonic() - start < 3


def test_run_missing_binary_returns_127():
    assert run(["nfc-player-no-such-binary"]).returncode == 127


def test_run_not_executable_returns_126(tmp_path):
    script = tmp_path / "script.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o644)
    assert run([str(script)]).returncode == 126


def test_run_rejects_a_single_string():
    with pytest.raises(TypeError):
        run("ls -l")


def test_run_never_logs_argv(caplog):
    caplog.set_level(TRACE)
    secret = "psk-do-not-log"
    results = [
        run([PY, "-c", "pass", secret]),
        run([PY, "-c", "import time; time.sleep(5)", secret], timeout=0.2),
        run(["nfc-player-no-such-binary", secret]),
    ]
    assert caplog.records
    assert secret not in caplog.text
    assert all(secret not in result.stderr for result in results)
