"""FDDB-Import über den authentifizierten CSV-Export.
Auth = persistenter Login-Cookie `fddb` (server/.env: FDDB_COOKIE), optional PHPSESSID.
Export: komplette Tagebuch-Historie als CSV (sep=';', decimal=',', kJ). Vollabzug -> ersetzt source='fddb'.

CSV-Spalten (verifiziert): datum_tag_monat_jahr_stunde_minute (DD.MM.YYYY HH:MM), bezeichnung,
interne_id, kj, kj_aktivitaeten, fett_g, kh_g, protein_g.  Energie kcal = kj / 4.184.
"""
from __future__ import annotations

import hashlib
import io

import httpx
import pandas as pd
from sqlalchemy import delete, func, select
from sqlmodel import Session

from ..config import settings
from ..db import count_rows, engine, upsert
from ..models import NutritionEntry

SOURCE = "fddb"
EXPORT = "https://fddb.info/db/i18n/exporter/?lang=de&action=diary&type=csv"
ACCOUNT = "https://fddb.info/db/i18n/account/?lang=de"
LOGIN = "https://fddb.info/db/i18n/account/?lang=de&action=login"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Milon/0.1"
KJ_PER_KCAL = 4.184


def _num(x) -> float | None:
    if x is None:
        return None
    s = str(x).strip().replace(",", ".")
    if s in ("", "nan", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _establish_session(c: httpx.Client) -> None:
    """Authentifiziert den Client: bevorzugt programmatischer Login (frischer Cookie,
    kein Ablaufproblem), sonst gespeicherter Cookie aus server/.env."""
    if settings.fddb_user and settings.fddb_pw:
        c.get(ACCOUNT)  # PHPSESSID setzen
        r = c.post(LOGIN, data={
            "loginemailorusername": settings.fddb_user,
            "loginpassword": settings.fddb_pw,
            "returnurl": "",
        })
        if "loginsuccess" in str(r.url) or "fddb" in c.cookies:
            return
    # Fallback: gespeicherter Cookie
    if settings.fddb_cookie:
        c.cookies.set("fddb", settings.fddb_cookie, domain="fddb.info")
        if settings.fddb_phpsessid:
            c.cookies.set("PHPSESSID", settings.fddb_phpsessid, domain="fddb.info")


def fetch_csv() -> str:
    if not ((settings.fddb_user and settings.fddb_pw) or settings.fddb_cookie):
        raise RuntimeError("FDDB-Zugang fehlt (FDDB_USER/FDDB_PW oder FDDB_COOKIE in server/.env)")
    with httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": UA}) as c:
        _establish_session(c)
        r = c.get(EXPORT)
        r.raise_for_status()
        text = r.text
    if "Keine Daten" in text[:60] or ";" not in text[:200]:
        raise RuntimeError("FDDB-Export leer / nicht authentifiziert (Login & Cookie geprueft).")
    return text


def parse_csv(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text), sep=";", dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    return df


def import_fddb(full: bool = False) -> dict:
    df = parse_csv(fetch_csv())

    seen: set = set()
    uniq: list[dict] = []
    for _, r in df.iterrows():
        dt = pd.to_datetime(r.get("datum_tag_monat_jahr_stunde_minute"),
                            format="%d.%m.%Y %H:%M", errors="coerce")
        if pd.isna(dt):
            continue
        kj = _num(r.get("kj"))
        kcal = round(kj / KJ_PER_KCAL, 1) if kj is not None else None
        raw_id = (r.get("interne_id") or "").strip()
        # NULL/leere interne_id -> stabiler Surrogat-Schluessel (sonst greift das Dedup nicht)
        fid = raw_id or ("h:" + hashlib.sha1(
            f"{dt.isoformat()}|{(r.get('bezeichnung') or '')}|{kcal}".encode("utf-8")).hexdigest()[:14])
        d = dict(
            eaten_at=dt.to_pydatetime(),
            description=(r.get("bezeichnung") or None),
            fddb_id=fid,
            kcal=kcal,
            fat_g=_num(r.get("fett_g")),
            carb_g=_num(r.get("kh_g")),
            protein_g=_num(r.get("protein_g")),
            source=SOURCE,
        )
        key = (d["eaten_at"], fid, kcal)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(d)

    with Session(engine) as s:
        if full:
            s.execute(delete(NutritionEntry).where(NutritionEntry.source == SOURCE))
        before = count_rows(s, NutritionEntry, SOURCE)
        upsert(s, NutritionEntry, uniq, ["eaten_at", "fddb_id", "kcal"])  # Append: nur neue Eintraege
        s.commit()
        after = count_rows(s, NutritionEntry, SOURCE)

    return {"mode": "full" if full else "incremental", "rows_csv": int(len(df)),
            "new": after - before, "total": after, "columns": list(df.columns)}


if __name__ == "__main__":
    from ..db import init_db

    init_db()
    res = import_fddb()
    print("FDDB-Import:", {k: v for k, v in res.items() if k != "columns"})
    print("Spalten:", res["columns"])
    with Session(engine) as s:
        mn, mx = s.execute(select(func.min(NutritionEntry.eaten_at), func.max(NutritionEntry.eaten_at))).first()
        total = s.execute(select(func.count()).select_from(NutritionEntry)).scalar_one()
        print(f"Einträge={total}  Zeitraum={mn} .. {mx}")
        # Beispiel: kcal-Summe der letzten 3 erfassten Tage
        rows = s.execute(
            select(func.date(NutritionEntry.eaten_at), func.round(func.sum(NutritionEntry.kcal)))
            .group_by(func.date(NutritionEntry.eaten_at))
            .order_by(func.date(NutritionEntry.eaten_at).desc()).limit(3)
        ).all()
        print("Letzte erfasste Tage (kcal):")
        for day, kcal in rows:
            print(f"  {day}: {kcal} kcal")
