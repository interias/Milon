from datetime import date, datetime, timezone
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlmodel import SQLModel, Session, create_engine, select

from app.models import RunBestEffort

from app.config import Settings, watch_source_for
from app.ingest import health_connect as hc


def test_watch_switch_requires_a_source():
    with pytest.raises(ValueError, match="WATCH_SOURCE_PACKAGE"):
        Settings(_env_file=None, watch_source_switch_date=date(2026, 9, 25))


def test_source_selection_keeps_history():
    config = SimpleNamespace(steps_source_package="old", watch_source_package="new",
                             watch_source_switch_date=date(2026, 9, 25))
    assert watch_source_for(date(2026, 9, 24), config) == "old"
    assert watch_source_for(date(2026, 9, 25), config) == "new"


@pytest.mark.parametrize("preserve_legacy", [False, True])
def test_import_selects_the_watch_per_date(tmp_path, preserve_legacy):
    path = tmp_path / "source.db"
    with sqlite3.connect(path) as con:
        con.executescript("""
            CREATE TABLE application_info_table(row_id, package_name);
            INSERT INTO application_info_table VALUES (1,'old'),(2,'new');
            CREATE TABLE weight_record_table(time, zone_offset, weight, app_info_id);
            CREATE TABLE body_fat_record_table(time, zone_offset, percentage, app_info_id);
            CREATE TABLE distance_record_table(start_time,end_time,distance,app_info_id);
            CREATE TABLE exercise_session_record_table(uuid,start_time,start_zone_offset,
                end_time,exercise_type,app_info_id);
            CREATE TABLE vo2_max_record_table(time,zone_offset,vo2_milliliters_per_minute_kilogram);
            CREATE TABLE steps_record_table(local_date,count,app_info_id);
            CREATE TABLE resting_heart_rate_record_table(time,zone_offset,beats_per_minute,app_info_id);
            CREATE TABLE heart_rate_record_table(row_id,app_info_id);
            INSERT INTO heart_rate_record_table VALUES (1,1),(2,2);
            CREATE TABLE heart_rate_record_series_table(parent_key,epoch_millis,beats_per_minute);
            CREATE TABLE SpeedRecordTable(row_id,app_info_id);
            INSERT INTO SpeedRecordTable VALUES (1,1),(2,2);
            CREATE TABLE speed_record_table(parent_key,epoch_millis,speed);
        """)
        for day in (24, 25, 26):
            start = int(datetime(2026, 9, day, 10, tzinfo=timezone.utc).timestamp() * 1000)
            epoch_day = (date(2026, 9, day) - date(1970, 1, 1)).days
            for app, distance, hr in ((1, 1000, 140), (2, 2000, 160)):
                if day == 26 and app == 2:
                    continue
                con.execute("INSERT INTO exercise_session_record_table VALUES (?, ?, 0, ?, 33, ?)",
                            (f"{day}-{app}", start, start + 600000, app))
                con.execute("INSERT INTO distance_record_table VALUES (?,?,?,?)",
                            (start, start + 600000, distance, app))
                con.execute("INSERT INTO steps_record_table VALUES (?,?,?)", (epoch_day, app * 3000, app))
                con.execute("INSERT INTO resting_heart_rate_record_table VALUES (?,0,?,?)",
                            (start, 60 - app * 5, app))
                con.executemany("INSERT INTO heart_rate_record_series_table VALUES (?,?,?)",
                                [(app, start + t * 1000, hr) for t in range(601)])
                con.executemany("INSERT INTO speed_record_table VALUES (?,?,?)",
                                [(app, start + t * 1000, app + 2) for t in range(601)])
        # New-watch missing day must remain a gap, not import an old/phone value.
        con.execute("INSERT INTO steps_record_table VALUES (?,9999,1)",
                    ((date(2026, 9, 26) - date(1970, 1, 1)).days,))
    config = SimpleNamespace(body_source_package="", body_weight_min_kg=None,
                             body_weight_max_kg=None, steps_source_package="old",
                             watch_source_package="new", watch_source_switch_date=date(2026, 9, 25),
                             watch_source_legacy_session_ids=["26-1"] if preserve_legacy else [])
    with patch.object(hc, "settings", config):
        data = hc.read_health_connect(path)
    sessions = sorted(data["sessions"], key=lambda s: s["started_at"])
    assert [s["external_id"] for s in sessions] == ["24-1", "25-2"] + (["26-1"] if preserve_legacy else [])
    assert [s["distance_km"] for s in sessions] == [1, 2] + ([1] if preserve_legacy else [])
    assert [s["avg_hr"] for s in sessions] == [140, 160] + ([140] if preserve_legacy else [])
    assert [s["steps"] for s in sorted(data["steps"], key=lambda s: s["day"])] == [3000, 6000]
    assert [s["bpm"] for s in sorted(data["resting"], key=lambda s: s["day"])] == [55, 50]
    assert {s["external_id"]: s["seconds"] for s in data["best_efforts"]} == {"24-1": 600, **({"26-1": 600} if preserve_legacy else {})}
    assert data["best_efforts_invalid_ids"] == ["25-2"]
    windows = data["run_windows"]
    assert set(windows["session_ids"]) == ({"24-1", "25-2"} | ({"26-1"} if preserve_legacy else set()))
    assert {r["external_id"]: r["hr_bpm"] for r in windows["rows"]} == {"24-1": 140, "25-2": 160, **({"26-1": 140} if preserve_legacy else {})}

    target = create_engine(f"sqlite:///{tmp_path / 'target.db'}")
    SQLModel.metadata.create_all(target)
    with Session(target) as session:
        for external_id in ("25-2", "missing-raw"):
            session.add(RunBestEffort(external_id=external_id, distance_m=1000,
                                     seconds=123, started_at=datetime(2026, 9, 25)))
        session.commit()
    with patch.object(hc, "settings", config), patch.object(hc, "engine", target):
        hc.import_health_connect(path)
    with Session(target) as session:
        rows = session.exec(select(RunBestEffort)).all()
        assert "25-2" not in {r.external_id for r in rows}
        assert "missing-raw" in {r.external_id for r in rows}
    target.dispose()
