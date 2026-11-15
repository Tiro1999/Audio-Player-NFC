"""Tests for nfc_player.nfc.reader with a fake PN532 (no hardware)."""

import dataclasses
import itertools
import logging
import sys
import threading
import time
import types

import ndef
import pytest

from nfc_player.nfc import reader
from nfc_player.nfc.ndef import extract_ndef_message
from nfc_player.nfc.reader import Pn532Reader, ReaderError, TagRead, open_reader, read_capacity

CC_NTAG213 = bytes.fromhex("E1101200")  # 144 bytes of user memory
CC_NTAG215 = bytes.fromhex("E1103E00")  # 496 bytes
CC_NTAG216 = bytes.fromhex("E1106D00")  # 872 bytes
LOCK_TLV_NTAG213 = bytes.fromhex("0103A00C34")  # factory Lock Control TLV
UID = bytes.fromhex("04A1B2C3D4E5F6")
USER_START = 16  # page 4 in a tag image
SPOTIFY_URL = "https://open.spotify.com/track/abc"


def i2c_error() -> OSError:
    return OSError(121, "Remote I/O error")  # PN532 not answering on the bus


def ack_error() -> RuntimeError:
    return RuntimeError("Did not receive expected ACK")


def encode(*records: ndef.Record) -> bytes:
    return b"".join(ndef.message_encoder(records))


def ndef_tlv(message: bytes) -> bytes:
    """NDEF message TLV plus terminator; 3-byte length from 255 bytes on."""
    if len(message) < 0xFF:
        return bytes([0x03, len(message)]) + message + b"\xfe"
    return b"\x03\xff" + len(message).to_bytes(2, "big") + message + b"\xfe"


def tag_image(cc: bytes, user_data: bytes) -> bytes:
    """Memory from page 0: UID and lock pages, CC (page 3), user data, then 4 config pages."""
    return bytes(12) + cc + user_data.ljust(cc[2] * 8, b"\x00") + bytes(16)


class FakePn532:
    """Stand-in for adafruit_pn532: a memory image, scripted polls and bad reads."""

    firmware_version = (0x32, 1, 6, 7)

    def __init__(self, memory=b"", polls=(), bad_reads=None, sam_error=None):
        self.memory = memory
        self.polls = list(polls)  # read_passive_target results: UID, None or an exception
        # Per page, outcomes of the next reads: an exception to raise or a wrong block to return.
        self.bad_reads = {page: iter(outcomes) for page, outcomes in (bad_reads or {}).items()}
        self.sam_error = sam_error
        self.calls = []

    def read_passive_target(self, timeout=1):
        self.calls.append(("poll", timeout))
        result = self.polls.pop(0) if self.polls else None
        if isinstance(result, Exception):
            raise result
        return result

    def mifare_classic_read_block(self, block_number):
        self.calls.append(("read", block_number))
        bad = next(self.bad_reads.get(block_number, iter(())), None)
        if isinstance(bad, Exception):
            raise bad
        if bad is not None:
            return bad
        block = self.memory[block_number * 4 : block_number * 4 + 16]
        return bytearray(block) if len(block) == 16 else None  # None like a NAK

    def SAM_configuration(self):
        self.calls.append(("sam", None))
        if self.sam_error is not None:
            raise self.sam_error

    @property
    def read_pages(self):
        return [value for name, value in self.calls if name == "read"]

    @property
    def poll_count(self):
        return sum(name == "poll" for name, _ in self.calls)


@pytest.fixture
def sleeps(monkeypatch):
    """Records the retry delays instead of sleeping."""
    delays = []
    monkeypatch.setattr(reader.time, "sleep", delays.append)
    return delays


@pytest.fixture
def hardware(monkeypatch):
    """Fake board, busio and adafruit_pn532 modules; returns the PN532 and the constructor calls."""
    pn532 = FakePn532()
    created = []

    def pn532_i2c(i2c, *, debug):
        created.append((i2c, debug))
        return pn532

    monkeypatch.setitem(sys.modules, "board", types.SimpleNamespace(SCL="SCL", SDA="SDA"))
    monkeypatch.setitem(sys.modules, "busio", types.SimpleNamespace(I2C=lambda scl, sda: ("i2c", scl, sda)))
    monkeypatch.setitem(sys.modules, "adafruit_pn532", types.ModuleType("adafruit_pn532"))
    monkeypatch.setitem(sys.modules, "adafruit_pn532.i2c", types.SimpleNamespace(PN532_I2C=pn532_i2c))
    return pn532, created


def test_tag_read_holds_uid_and_memory():
    tag = TagRead(uid="04A1B2C3", memory=None)
    assert (tag.uid, tag.memory) == ("04A1B2C3", None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        tag.uid = "x"


@pytest.mark.parametrize(
    ("cc", "capacity"),
    [
        (CC_NTAG213, 144),
        (CC_NTAG215, 496),
        (CC_NTAG216, 872),
        (bytes.fromhex("00103E00"), 144),
        (b"\xe1", 144),
    ],
    ids=["ntag213", "ntag215", "ntag216", "bad magic", "too short"],
)
def test_read_capacity(cc, capacity):
    assert read_capacity(cc) == capacity


def test_read_memory_stops_after_tlv():
    image = tag_image(CC_NTAG215, ndef_tlv(encode(ndef.UriRecord("spotify:track:abc"))))  # TLV ends at 24
    fake = FakePn532(image)
    assert Pn532Reader(fake).read_memory() == image[USER_START : USER_START + 28]
    assert fake.read_pages == [3, 7]


def test_read_memory_ntag213_with_lock_tlv():
    message = encode(ndef.UriRecord(SPOTIFY_URL))
    fake = FakePn532(tag_image(CC_NTAG213, LOCK_TLV_NTAG213 + ndef_tlv(message)))
    assert extract_ndef_message(Pn532Reader(fake).read_memory()) == message
    assert fake.read_pages == [3, 7, 11]


def test_read_memory_ntag216_long_message():
    message = encode(ndef.TextRecord("x" * 590))
    assert len(message) == 600
    fake = FakePn532(tag_image(CC_NTAG216, ndef_tlv(message)))
    assert extract_ndef_message(Pn532Reader(fake).read_memory()) == message
    assert len(fake.read_pages) == 38  # 12 bytes after the CC + 37 * 16 = 604 = 4-byte header + 600


def test_read_memory_stops_at_terminator():
    fake = FakePn532(tag_image(CC_NTAG216, b"\xfe"))
    assert Pn532Reader(fake).read_memory() == b"\xfe" + bytes(11)
    assert fake.read_pages == [3]


def test_read_memory_truncates_to_capacity():
    fake = FakePn532(tag_image(CC_NTAG213, b""))  # NULL TLVs only, no NDEF message
    assert Pn532Reader(fake).read_memory() == bytes(144)
    assert fake.read_pages == list(range(3, 40, 4))


def test_read_memory_partial_on_error(sleeps):
    image = tag_image(CC_NTAG215, ndef_tlv(encode(ndef.UriRecord(SPOTIFY_URL))))
    fake = FakePn532(image, bad_reads={7: itertools.repeat(i2c_error())})
    assert Pn532Reader(fake).read_memory(retries=3) == image[USER_START : USER_START + 12]
    assert fake.read_pages == [3, 7] * 4  # first pass plus 3 retries
    assert sleeps == [0.15] * 3


def test_read_memory_retry_recovers(sleeps):
    message = encode(ndef.UriRecord(SPOTIFY_URL))
    fake = FakePn532(tag_image(CC_NTAG215, ndef_tlv(message)), bad_reads={7: [ack_error()]})
    assert extract_ndef_message(Pn532Reader(fake).read_memory()) == message
    assert fake.read_pages == [3, 7, 3, 7, 11]
    assert sleeps == [0.15]


def test_read_memory_none_when_nothing_read(sleeps):
    fake = FakePn532()  # every read returns None, as for a tag without NTAG memory
    assert Pn532Reader(fake).read_memory() is None
    assert fake.read_pages == [3] * 4


def test_read_memory_short_block_is_a_failed_read(sleeps):
    message = encode(ndef.UriRecord(SPOTIFY_URL))
    fake = FakePn532(tag_image(CC_NTAG215, ndef_tlv(message)), bad_reads={7: [bytearray(4)]})
    assert extract_ndef_message(Pn532Reader(fake).read_memory()) == message
    assert fake.read_pages == [3, 7, 3, 7, 11]


def test_read_memory_never_logs_tag_bytes(caplog, sleeps):
    caplog.set_level(logging.DEBUG, logger="nfc_player.nfc")
    image = tag_image(CC_NTAG215, ndef_tlv(encode(ndef.UriRecord("spotify:track:SECRET42"))))
    fake = FakePn532(image, bad_reads={7: [i2c_error()]})
    assert Pn532Reader(fake).read_memory() is not None
    assert caplog.records
    assert "SECRET42" not in caplog.text
    assert b"SECRET42".hex() not in caplog.text.lower()


def test_wait_for_tag_uid_hex():
    fake = FakePn532(polls=[bytearray(UID), None])
    nfc = Pn532Reader(fake)
    assert nfc.wait_for_tag() == "04A1B2C3D4E5F6"
    assert nfc.wait_for_tag(timeout=0.2) is None
    assert fake.calls == [("poll", 0.5), ("poll", 0.2)]


def test_wait_for_tag_wraps_runtime_error():
    error = ack_error()
    with pytest.raises(ReaderError) as excinfo:
        Pn532Reader(FakePn532(polls=[error])).wait_for_tag()
    assert excinfo.value.__cause__ is error


def test_wait_for_removal_counts_errors_as_miss():
    fake = FakePn532(polls=[i2c_error(), ack_error(), None])
    Pn532Reader(fake).wait_for_removal(threading.Event(), poll_interval=0)
    assert fake.calls == [("poll", 0.5)] * 3 + [("sam", None)]


def test_wait_for_removal_needs_consecutive_misses():
    fake = FakePn532(polls=[None, None, UID, None, None, None])
    Pn532Reader(fake).wait_for_removal(threading.Event(), poll_interval=0)
    assert fake.poll_count == 6


def test_wait_for_removal_returns_when_stopped():
    stop = threading.Event()
    stop.set()
    fake = FakePn532(polls=[UID] * 10)  # the tag stays on the reader
    start = time.monotonic()
    Pn532Reader(fake).wait_for_removal(stop)
    assert time.monotonic() - start < 0.1
    assert fake.poll_count == 0


def test_wait_for_removal_wakes_up_on_stop():
    stop = threading.Event()
    fake = FakePn532(polls=[UID] * 10)  # the tag stays on the reader
    timer = threading.Timer(0.05, stop.set)
    timer.start()
    start = time.monotonic()
    Pn532Reader(fake).wait_for_removal(stop, poll_interval=5)
    timer.join()
    assert time.monotonic() - start < 1


def test_wait_for_removal_resets_reader():
    fake = FakePn532(polls=[UID, None, None, None])
    Pn532Reader(fake).wait_for_removal(threading.Event(), poll_interval=0)
    assert fake.calls[-1] == ("sam", None)
    assert fake.calls.count(("sam", None)) == 1


def test_reset_swallows_errors():
    fake = FakePn532(sam_error=i2c_error())
    Pn532Reader(fake).reset()
    assert fake.calls == [("sam", None)]


def test_open_reader_configures_sam(hardware, caplog):
    pn532, created = hardware
    caplog.set_level(logging.INFO, logger="nfc_player.nfc")
    assert isinstance(open_reader(), Pn532Reader)
    assert created == [(("i2c", "SCL", "SDA"), False)]
    assert pn532.calls == [("sam", None)]
    assert "1.6" in caplog.text


def test_open_reader_wraps_hardware_errors(hardware):
    pn532, _ = hardware
    pn532.sam_error = i2c_error()
    with pytest.raises(ReaderError):
        open_reader()


def test_open_reader_without_hardware_libraries(monkeypatch):
    monkeypatch.setitem(sys.modules, "board", None)  # import fails, as on a PC
    with pytest.raises(ReaderError):
        open_reader()
