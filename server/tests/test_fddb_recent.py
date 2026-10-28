"""FDDB-Import ersetzt die letzten Tage ganz: geänderte und gelöschte Einträge zählen nicht doppelt."""
from datetime import date, timedelta

from sqlmodel import Session, SQLModel, create_engine, select

from app.ingest import fddb
from app.models import NutritionEntry


def _csv(rows):
    head = "datum_tag_monat_jahr_stunde_minute;bezeichnung;interne_id;kj;kj_aktivitaeten;fett_g;kh_g;protein_g\n"
    return head + "".join(f"{d.strftime('%d.%m.%Y')} {t};{n};{i};{kj};0;1;1;1\n" for d, t, n, i, kj in rows)


def test_recent_days_replaced(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(fddb, "engine", eng)
    today, old = date.today(), date.today() - timedelta(days=10)
    first = [(old, "08:00", "Alt", "1", 418.4), (today, "08:00", "Müsli", "2", 418.4), (today, "12:00", "Pizza", "3", 4184)]
    monkeypatch.setattr(fddb, "fetch_csv", lambda: _csv(first))
    fddb.import_fddb()
    # tagsüber: Müsli-Menge geändert (gleiche interne_id, neue kJ), Pizza gelöscht
    second = [(old, "08:00", "Alt", "1", 418.4), (today, "08:00", "Müsli", "2", 836.8)]
    monkeypatch.setattr(fddb, "fetch_csv", lambda: _csv(second))
    fddb.import_fddb()
    with Session(eng) as s:
        rows = s.exec(select(NutritionEntry)).all()
    assert sorted(round(r.kcal) for r in rows) == [100, 200]
