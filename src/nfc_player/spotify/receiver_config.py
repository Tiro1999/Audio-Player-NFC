"""Receiver config: renders go-librespot's config.yml from the device config (ExecStartPre).

Runs as the service user. Only config.yml is replaced; every other file in RECEIVER_DIR,
above all state.json with the stored Spotify credentials, stays untouched.
"""

import argparse
import logging

from nfc_player.core import paths
from nfc_player.core.build_info import load_build_info
from nfc_player.core.config import DEFAULT_DEVICE_NAME, ConfigError, load_config, write_text_atomic
from nfc_player.core.log import setup_logging
from nfc_player.core.validate import device_name_error

log = logging.getLogger(__name__)

# Only keys of go-librespot's schema (additionalProperties: false).
# The API has no auth, so it stays bound to 127.0.0.1.
_TEMPLATE = """\
device_name: "{device_name}"
device_type: speaker
audio_backend: pulseaudio
bitrate: 160
credentials:
  type: zeroconf
  zeroconf:
    persist_credentials: true
server:
  enabled: true
  address: 127.0.0.1
  port: {port}
"""


def render_receiver_config(device_name: str, *, port: int = 3678) -> str:
    """config.yml for go-librespot; ValueError for a name that could break out of its YAML string."""
    error = device_name_error(device_name)
    if error:
        raise ValueError(error)
    return _TEMPLATE.format(device_name=device_name, port=port)


def load_device_name() -> str:
    """The receiver name from the device config; DEFAULT_DEVICE_NAME with a warning if it is unusable."""
    try:
        return load_config(paths.DEVICE_CONFIG).device_name
    except ConfigError as exc:
        log.warning("Device config invalid (%s); receiver name '%s'", exc, DEFAULT_DEVICE_NAME)
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        log.warning(
            "Cannot read %s (%s); receiver name '%s'", paths.DEVICE_CONFIG, reason, DEFAULT_DEVICE_NAME
        )
    return DEFAULT_DEVICE_NAME


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the receiver config.yml from the device config.")
    parser.parse_args(argv)
    setup_logging(load_build_info().maturity)
    name = load_device_name()
    target = paths.RECEIVER_DIR / "config.yml"
    try:
        write_text_atomic(target, render_receiver_config(name), mode=0o600)
    except OSError as exc:
        log.error("Cannot write %s: %s", target, exc.strerror or exc)
        return 1
    log.info("Receiver config written (name '%s')", name)
    shadow = paths.RECEIVER_DIR / "config.yaml"
    if shadow.exists():
        log.warning("%s takes precedence over config.yml; remove it", shadow)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
