"""QN protocol core of the scale receiver (tools/scale/qn.py), fed with the real CS20L frames of 2026-11-23."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "scale"))
from qn import QnSession, hexs, parse_live, parse_stored, qn_time_to_iso, with_checksum  # noqa: E402

H = bytes.fromhex
NOW = 1795454462.0  # 2026-11-23 17:21:02 UTC (time the phone sent in the second test)


def handshake(s: QnSession, now: float = NOW) -> list[str]:
    out = []
    for frame in ("12 12 ff 9f 35 05 00 05 ff 12 07 15 00 01 05 9f 32 05", "14 0b ff 01 00 01 09 03 00 00 2c",
                  "21 05 ff 01 26", "a1 06 04 fe 01 aa", "a1 06 02 01 00 aa"):
        out += [f"{t}:{hexs(d)}" for t, d in s.on_packet(H(frame), now)]
    return out


def test_handshake_writes_match_the_browser_driver_byte_for_byte():
    s = QnSession(NOW)
    out = handshake(s)
    assert out == [
        "write:13 09 ff 01 10 00 00 00 2c",
        "time:02 2e ec 96 32",
        "write:20 08 ff 2e ec 96 32 09",
        "write:a0 0d 04 fe 00 00 00 00 00 00 00 00 af",
        "write:a0 0d 02 01 00 08 00 21 06 b8 04 02 9d",
        "write:22 06 ff 00 03 2a",
    ]
    assert (s.protocol_type, s.factor) == (0xFF, 10)
    assert hexs(s.history_query()) == "22 06 ff 00 03 2a"


def test_old_stored_record_goes_to_backlog_with_its_own_time():
    s = QnSession(NOW)
    handshake(s)
    s.on_packet(H("23 14 ff 01 01 f0 ea e6 96 32 1d fb 00 00 00 00 00 00 00 d8"), NOW)
    for frame in ("24 10 ff 00 00 00 00 00 00 00 00 00 00 00 00 33", "25 0f ff 00 00 00 00 00 00 00 00 00 00 00 00 33",
                  "23 14 ff 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 36"):
        assert s.on_packet(H(frame), NOW) == []
    assert s.final is None
    assert [(r["weightKg"], r["source"], r["timestamp"]) for r in s.backlog] == [(76.75, "stored", "2026-11-23T16:58:34.000Z")]
    assert s.history_query() is not None  # keep asking for this weighing


def test_fresh_stored_record_is_this_weighing_and_acked():
    s = QnSession(NOW)
    handshake(s)
    t = int(NOW) - 946_702_800 + 20  # weighed 20 s after connecting
    d = with_checksum([0x23, 0x14, 0xFF, 1, 1, 0xF0, t & 0xFF, (t >> 8) & 0xFF, (t >> 16) & 0xFF, (t >> 24) & 0xFF,
                       0x1C, 0x93, 0, 0xF4, 0x01, 0xE0, 0x01, 0, 0, 0])
    out = s.on_packet(d, NOW + 25)
    assert [hexs(x) for _, x in out] == ["1f 05 ff 10 33"]
    assert (s.final["weightKg"], s.final["r1"], s.final["r2"]) == (73.15, 500, 480)
    assert s.history_query() is None
    assert s.on_packet(H("21 05 ff 01 26"), NOW) == []  # nothing after the weighing


def test_live_stable_frame_new_layout():
    s = QnSession(NOW)
    handshake(s)
    assert s.on_packet(with_checksum([0x10, 0x0E, 0xFF, 0x01, 0x00, 0x02, 0xBC, 0, 0, 0, 0, 0]), NOW) == []
    assert s.last_live == 70.0 and s.final is None
    out = s.on_packet(with_checksum([0x10, 0x0E, 0xFF, 0x01, 0x02, 0x02, 0xDB, 0x01, 0xF4, 0x01, 0xE0, 0]), NOW)
    assert out and s.final["source"] == "live" and s.final["weightKg"] == 73.1
    assert s.final["r1"] == 500


def test_parsers_and_clock_sanity():
    assert parse_live(H("10 0b ff 1b 58 01 01 f4 01 e0 00"), 100, 0xFF)["kg"] == 70
    assert parse_stored(H("23 05 01 00 00")) is None
    assert qn_time_to_iso(0, NOW) is None
    assert hexs(with_checksum([0xFF, 0xFF, 0xFF, 0])) == "ff ff ff fd"
