"""Heldenreise: Strecken-Verliese als Datei für die Uhr (GPX-Track bzw. FIT-Course).

Exportiert wird ausschließlich die öffentliche Verlies-Strecke (lat/lon aus `hero_dungeons.json`):
kein Heimatpunkt, keine Entfernungen zur Heimat, keine Läufe des Nutzers. Die Abschnittsgrenzen
(Ende jedes Abschnitts = Ort des Bosses) werden zu GPX-Wegpunkten bzw. FIT-Coursepoints.

Der FIT-Course-Encoder ist bewusst klein und ohne Abhängigkeit (FIT-Protokoll 2.0): Header + CRC,
`file_id`, `course`, `lap`, `event`, `record`, `course_point`. Zeitstempel sind synthetisch
(fester Start + Distanz/Referenztempo), damit die Datei als Course gültig ist.
"""
from __future__ import annotations

import math
import re
import struct
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

NAME_MAX = 15  # Garmin kürzt Kursnamen; FIT-String-Feld = 15 Zeichen + Nullbyte
_STOP = {"der", "die", "das", "des", "dem", "den", "von", "vom", "zum", "zur", "am", "im", "an", "in", "und"}
_SPECIAL = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}

REF_SPEED = 3.0  # m/s für synthetische Zeitstempel (~5:33 min/km)
_FIT_EPOCH = 631065600  # 1989-12-31T00:00:00Z in Unix-Sekunden
_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def short_name(name: str, limit: int = NAME_MAX) -> str:
    """Deterministischer ASCII-Kurzname ≤ `limit` Zeichen (Umlaute gefaltet, Füllwörter zuerst weg)."""
    s = "".join(_SPECIAL.get(c, c) for c in name)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    words = re.findall(r"[A-Za-z0-9]+", s)
    if len(" ".join(words)) > limit:
        words = [w for w in words if w.lower() not in _STOP] or words
    return " ".join(words)[:limit].rstrip()


def file_stem(name: str) -> str:
    return short_name(name).replace(" ", "_") or "route"


def _haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742000 * math.asin(math.sqrt(h))


def flatten(route: dict) -> tuple[list[tuple[float, float]], list[tuple[str, int]]]:
    """Abschnitte zu einer Polylinie; Marken = (Boss, Index des Abschnittsendes)."""
    pts: list[tuple[float, float]] = []
    marks: list[tuple[str, int]] = []
    for seg in route["segments"]:
        for p in seg["points"]:
            p = (float(p[0]), float(p[1]))
            if not pts or p != pts[-1]:
                pts.append(p)
        marks.append((seg["boss"], len(pts) - 1))
    return pts, marks


def _cumulative(pts) -> list[float]:
    out = [0.0]
    for a, b in zip(pts, pts[1:]):
        out.append(out[-1] + _haversine(a, b))
    return out


# --- GPX -----------------------------------------------------------------------------------------

def gpx_bytes(route: dict) -> bytes:
    pts, marks = flatten(route)
    name = short_name(route["name"])
    ns = "http://www.topografix.com/GPX/1/1"
    ET.register_namespace("", ns)
    root = ET.Element(f"{{{ns}}}gpx", {"version": "1.1", "creator": "Milon"})
    meta = ET.SubElement(root, f"{{{ns}}}metadata")
    ET.SubElement(meta, f"{{{ns}}}name").text = name
    for boss, i in marks:
        w = ET.SubElement(root, f"{{{ns}}}wpt", {"lat": f"{pts[i][0]:.5f}", "lon": f"{pts[i][1]:.5f}"})
        ET.SubElement(w, f"{{{ns}}}name").text = boss
    trk = ET.SubElement(root, f"{{{ns}}}trk")
    ET.SubElement(trk, f"{{{ns}}}name").text = name
    seg = ET.SubElement(trk, f"{{{ns}}}trkseg")
    for la, lo in pts:
        ET.SubElement(seg, f"{{{ns}}}trkpt", {"lat": f"{la:.5f}", "lon": f"{lo:.5f}"})
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


# --- FIT (Course) --------------------------------------------------------------------------------

_CRC = [0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
        0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400]


def fit_crc(data: bytes, crc: int = 0) -> int:
    for b in data:
        crc = ((crc >> 4) & 0x0FFF) ^ _CRC[crc & 0xF] ^ _CRC[b & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ _CRC[crc & 0xF] ^ _CRC[(b >> 4) & 0xF]
    return crc


# Basistyp -> (Typ-Byte, struct-Format, Größe); Strings tragen ihre Länge im Feld
_ENUM, _U8, _U16, _S32, _U32, _STR, _U32Z = 0x00, 0x02, 0x84, 0x85, 0x86, 0x07, 0x8C
_FMT = {_ENUM: "B", _U8: "B", _U16: "H", _S32: "i", _U32: "I", _U32Z: "I"}
_SIZE = {_ENUM: 1, _U8: 1, _U16: 2, _S32: 4, _U32: 4, _U32Z: 4}


class _Writer:
    def __init__(self) -> None:
        self.buf = bytearray()
        self.defs: dict[int, bytes] = {}

    def message(self, local: int, global_num: int, fields: list[tuple[int, int, object, int]]) -> None:
        """Definition + Datensatz. Feld = (Feldnummer, Basistyp, Wert, Stringlänge)."""
        d = bytearray([0x40 | local, 0, 0]) + struct.pack("<HB", global_num, len(fields))
        for num, typ, _, slen in fields:
            d += bytes([num, slen if typ == _STR else _SIZE[typ], typ])
        row = bytearray([local])
        for _, typ, val, slen in fields:
            if typ == _STR:
                row += str(val).encode("ascii", "ignore")[: slen - 1].ljust(slen, b"\0")
            else:
                row += struct.pack("<" + _FMT[typ], val)
        if self.defs.get(local) != bytes(d):  # Definition nur bei Wechsel des Layouts
            self.defs[local] = bytes(d)
            self.buf += d
        self.buf += row


def _semicircles(deg: float) -> int:
    return round(deg * 2147483648 / 180)


def fit_bytes(route: dict) -> bytes:
    pts, marks = flatten(route)
    name = short_name(route["name"])
    cum = _cumulative(pts)
    t0 = int(_START.timestamp()) - _FIT_EPOCH
    ts = [t0 + round(d / REF_SPEED) for d in cum]
    total_ms = round(cum[-1] / REF_SPEED * 1000)
    w = _Writer()
    w.message(0, 0, [(0, _ENUM, 6, 0), (1, _U16, 255, 0), (2, _U16, 0, 0), (3, _U32Z, 1, 0), (4, _U32, t0, 0)])
    w.message(1, 31, [(4, _ENUM, 1, 0), (5, _STR, name, NAME_MAX + 1)])
    w.message(2, 19, [(253, _U32, ts[-1], 0), (2, _U32, t0, 0),
                      (3, _S32, _semicircles(pts[0][0]), 0), (4, _S32, _semicircles(pts[0][1]), 0),
                      (5, _S32, _semicircles(pts[-1][0]), 0), (6, _S32, _semicircles(pts[-1][1]), 0),
                      (7, _U32, total_ms, 0), (8, _U32, total_ms, 0), (9, _U32, round(cum[-1] * 100), 0)])
    w.message(3, 21, [(253, _U32, t0, 0), (0, _ENUM, 0, 0), (1, _ENUM, 0, 0), (4, _U8, 0, 0)])
    for (la, lo), d, t in zip(pts, cum, ts):
        w.message(4, 20, [(253, _U32, t, 0), (0, _S32, _semicircles(la), 0), (1, _S32, _semicircles(lo), 0),
                          (5, _U32, round(d * 100), 0)])
    for n, (boss, i) in enumerate(marks):
        w.message(5, 32, [(254, _U16, n, 0), (1, _U32, ts[i], 0),
                          (2, _S32, _semicircles(pts[i][0]), 0), (3, _S32, _semicircles(pts[i][1]), 0),
                          (4, _U32, round(cum[i] * 100), 0), (5, _ENUM, 0, 0), (6, _STR, short_name(boss), NAME_MAX + 1)])
    w.message(3, 21, [(253, _U32, ts[-1], 0), (0, _ENUM, 0, 0), (1, _ENUM, 4, 0), (4, _U8, 0, 0)])
    head = struct.pack("<BBHI4s", 14, 0x20, 2132, len(w.buf), b".FIT")
    head += struct.pack("<H", fit_crc(head))
    body = head + bytes(w.buf)
    return body + struct.pack("<H", fit_crc(body))
