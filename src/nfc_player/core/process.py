"""Subprocess runner: argv lists only (never a shell), always with a timeout."""

import logging
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from nfc_player.core.log import TRACE

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Result:
    """Outcome of a command; stdout and stderr are decoded as UTF-8."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


Runner = Callable[..., Result]


def run(
    args: Sequence[str],
    *,
    timeout: float = 15.0,
    input: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Result:
    """Run a command and never raise for it: timeout → 124, missing binary → 127, not startable → 126.

    `env` adds variables to the current environment. Without `input`, stdin is /dev/null.
    Only the program name is logged: the arguments may hold secrets.
    """
    if isinstance(args, str):
        raise TypeError("args must be a list of arguments, not one string")
    program = os.path.basename(str(args[0]))
    try:
        completed = subprocess.run(
            list(args),
            input=input,
            stdin=subprocess.DEVNULL if input is None else None,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env={**os.environ, **env} if env else None,
            check=False,
        )
    except subprocess.TimeoutExpired:
        log.warning("%s timed out after %g s", program, timeout)
        return Result(124, "", f"{program}: timed out after {timeout:g} s")
    except FileNotFoundError:
        log.warning("%s not found", program)
        return Result(127, "", f"{program}: command not found")
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        log.warning("%s could not be started: %s", program, reason)
        return Result(126, "", f"{program}: {reason}")
    log.log(TRACE, "%s exited with %d", program, completed.returncode)
    return Result(completed.returncode, completed.stdout, completed.stderr)
