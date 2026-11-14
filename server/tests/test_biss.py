"""BISS import: day boundary, replacing recent days, cut-over date, and the statistics built on it."""
from datetime import date, datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import settings
from app.ingest import biss
from app.metrics import nutrition
from app.models import NutritionEntry, NutritionGoal

NOW = datetime(2026, 11, 15, 12)


def _entry(id_, day, eaten_at, name, kcal, protein, meal="lunch", **extra):
    return {"id": id_, "day": day, "eaten_at": eaten_at, "grams": 100.0, "meal": meal,
            "food": {"id": id_ * 10, "name": name, "brand": "Marke", "category": "other"},
            "macros": {"kcal": kcal, "protein": protein, "carbs": 10.0, "fat": 5.0},
            "group_id": None, "group_name": None, **extra}


def _day(day, entries):
    return {"date": day, "targets": {"kcal": 2400, "protein": 160, "carbs": 260, "fat": 75},
            "meals": [{"meal": "lunch", "entries": entries}]}


@pytest.fixture
def db(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(biss, "engine", eng)
    monkeypatch.setattr(nutrition, "engine", eng)
    monkeypatch.setattr(settings, "biss_since", date(2026, 11, 14))
    monkeypatch.setattr(settings, "nutrition_source", "biss")
    monkeypatch.setattr(nutrition, "_now", lambda: NOW)
    monkeypatch.setattr(nutrition, "protein_target", lambda: 135)
    return eng


def _serve(monkeypatch, days: dict):
    asked = []

    def fetch(wanted):
        asked.extend(wanted)
        return [days.get(d.isoformat(), _day(d.isoformat(), [])) for d in wanted]

    monkeypatch.setattr(biss, "fetch_days", fetch)
    return asked


def test_import_keeps_the_biss_day_and_never_reaches_before_the_cutover(db, monkeypatch):
    asked = _serve(monkeypatch, {
        "2026-11-14": _day("2026-11-14", [
            _entry(1, "2026-11-14", "2026-11-14T11:30:00Z", "Reis", 300, 6),
            # 01:15 local on the 15th, but BISS counts it to the 14th (04:00 boundary)
            _entry(2, "2026-11-14", "2026-11-15T00:15:00Z", "Quark", 150, 25),
        ]),
        "2026-11-15": _day("2026-11-15", [_entry(3, "2026-11-15", "2026-11-15T07:00:00Z", "Ei", 90, 7, "breakfast")]),
    })
    res = biss.import_biss(now=NOW)
    assert asked == [date(2026, 11, 14), date(2026, 11, 15)]  # 13.11. is FDDB's day
    assert res["entries"] == 3 and res["changed"]
    with Session(db) as s:
        rows = {r.fddb_id: r for r in s.exec(select(NutritionEntry)).all()}
        goal = s.get(NutritionGoal, date(2026, 11, 15))
    assert rows["biss:1"].eaten_at == datetime(2026, 11, 14, 12, 30)  # UTC → Berlin
    assert rows["biss:2"].eaten_at == datetime(2026, 11, 14, 23, 59, 59)
    assert rows["biss:3"].meal == "breakfast" and rows["biss:3"].brand == "Marke"
    assert goal.protein_g == 160 and goal.carb_g == 260


def test_edited_and_deleted_entries_replace_the_day_and_fddb_stays(db, monkeypatch):
    with Session(db) as s:
        s.add(NutritionEntry(eaten_at=datetime(2026, 11, 15, 8), kcal=500, fddb_id="x", source="fddb"))
        s.commit()
    _serve(monkeypatch, {"2026-11-15": _day("2026-11-15", [
        _entry(1, "2026-11-15", "2026-11-15T07:00:00Z", "Ei", 90, 7), _entry(2, "2026-11-15", "2026-11-15T08:00:00Z", "Brot", 200, 6)])})
    cursor = biss.import_biss(now=NOW)["cursor"]
    _serve(monkeypatch, {"2026-11-15": _day("2026-11-15", [_entry(1, "2026-11-15", "2026-11-15T07:00:00Z", "Ei", 180, 14)])})
    res = biss.import_biss(now=NOW)
    assert res["changed"] and res["cursor"] != cursor
    with Session(db) as s:
        rows = s.exec(select(NutritionEntry)).all()
    assert sorted((r.source, round(r.kcal)) for r in rows) == [("biss", 180), ("fddb", 500)]


def test_unchanged_diary_writes_nothing(db, monkeypatch):
    from app.models import SyncState
    _serve(monkeypatch, {"2026-11-15": _day("2026-11-15", [_entry(1, "2026-11-15", "2026-11-15T07:00:00Z", "Ei", 90, 7)])})
    first = biss.import_biss(now=NOW)
    with Session(db) as s:
        s.add(SyncState(source="biss", cursor=first["cursor"]))
        s.commit()
    assert biss.import_biss(now=NOW)["changed"] is False


def test_today_until_four_belongs_to_the_day_before():
    assert biss.biss_today(datetime(2026, 11, 15, 3, 59)) == date(2026, 11, 14)
    assert biss.biss_today(datetime(2026, 11, 15, 4, 0)) == date(2026, 11, 15)


def test_statistics_today_foods_and_meals(db, monkeypatch):
    with Session(db) as s:  # FDDB history with the amount in front of the name
        s.add(NutritionEntry(eaten_at=datetime(2026, 11, 13, 12), description="100 g Harzer Roller", kcal=125,
                             protein_g=30, carb_g=0, fat_g=1, fddb_id="f1", source="fddb"))
        s.add(NutritionEntry(eaten_at=datetime(2026, 11, 12, 12), description="1 Portion Harzer Roller", kcal=125,
                             protein_g=30, carb_g=0, fat_g=1, fddb_id="f2", source="fddb"))
        s.commit()
    _serve(monkeypatch, {"2026-11-15": _day("2026-11-15", [
        _entry(1, "2026-11-15", "2026-11-15T07:00:00Z", "Ei", 90, 7, "breakfast"),
        _entry(2, "2026-11-15", "2026-11-15T10:00:00Z", "Reis", 300, 6)])})
    biss.import_biss(now=NOW)

    today = nutrition.today()
    assert (today["date"], today["kcal"], today["protein"], today["carb"], today["entries"]) == ("2026-11-15", 390, 13, 20, 2)
    assert today["goal"] == {"kcal": 2400, "protein": 160, "carb": 260, "fat": 75}
    assert today["last_entry"] == "11:00" and today["avg7"]["protein"] == 30 and today["avg7_days"] == 2
    assert sum(today["split"].values()) in (99, 100, 101)

    foods = nutrition.foods(30)
    assert foods["favorites"][0]["name"] == "Harzer Roller" and foods["favorites"][0]["count"] == 2
    assert foods["protein"][0]["share"] == round(60 / 73 * 100)

    meals = nutrition.meals(30)
    assert [m["meal"] for m in meals["meals"]] == ["breakfast", "lunch"] and meals["recorded_days"] == 1
    assert meals["meals"][0]["protein_share"] == round(7 / 13 * 100)


def test_statistics_on_an_empty_diary(db):
    assert nutrition.today()["kcal"] == 0 and nutrition.today()["goal"] is None
    assert nutrition.foods()["favorites"] == [] and nutrition.meals()["meals"] == []
