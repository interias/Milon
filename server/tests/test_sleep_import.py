from datetime import date, datetime, timezone
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.ingest import health_connect as hc
from app.models import SleepSession


def config():
    return SimpleNamespace(body_source_package="", body_weight_min_kg=None, body_weight_max_kg=None,
                           steps_source_package="old", watch_source_package="new",
                           watch_source_switch_date=date(2026, 9, 25), watch_source_legacy_session_ids=[])


def source_database(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE application_info_table(row_id,package_name);
        INSERT INTO application_info_table VALUES (1,'old'),(2,'new');
        CREATE TABLE sleep_session_record_table(row_id,uuid,start_time,end_time,start_zone_offset,
            end_zone_offset,app_info_id);
        CREATE TABLE sleep_stages_table(parent_key,stage_start_time,stage_end_time,stage_type);
        CREATE TABLE weight_record_table(time,zone_offset,weight,app_info_id);
        CREATE TABLE body_fat_record_table(time,zone_offset,percentage,app_info_id);
        CREATE TABLE exercise_session_record_table(uuid,start_time,start_zone_offset,end_time,exercise_type,app_info_id);
        CREATE TABLE distance_record_table(start_time,end_time,distance,app_info_id);
        CREATE TABLE vo2_max_record_table(time,zone_offset,vo2_milliliters_per_minute_kilogram);
        CREATE TABLE steps_record_table(local_date,count,app_info_id);
    """)
    return con


def add_sleep(con, row_id, start, end, app, phases=True):
    con.execute("INSERT INTO sleep_session_record_table VALUES (?,?,?,?,7200,7200,?)",
                (row_id, str(row_id), start, end, app))
    if phases:
        midpoint = start + (end - start) // 2
        con.executemany("INSERT INTO sleep_stages_table VALUES (?,?,?,?)",
                        [(row_id, start, midpoint, 4), (row_id, midpoint, end, 1)])


def test_stage_durations_do_not_treat_awake_unknown_or_overlaps_as_sleep():
    end = 8 * 3_600_000
    result = hc._sleep_minutes(0, end, [(0, end // 2, 4), (end // 2, end, 1), (0, end // 2, 4)])
    assert result == {"asleep_minutes": 240, "awake_minutes": 240, "stage_coverage": 1}
    assert hc._sleep_minutes(0, end, []) == {"asleep_minutes": None, "awake_minutes": None, "stage_coverage": 0}
    assert hc._sleep_minutes(0, end, [(0, end, 0)])["asleep_minutes"] is None
    # Unknown interval and incompatible overlap both suppress the asleep estimate.
    assert hc._sleep_minutes(0, end, [(0, end // 2, 2)])["asleep_minutes"] is None
    assert hc._sleep_minutes(0, end, [(0, end, 2), (0, end // 2, 7)])["asleep_minutes"] is None
    assert hc._sleep_minutes(0, end, [(0, end // 2, 6), (end // 2, end, 3)])["asleep_minutes"] == 240


def test_sleep_source_selection_uses_waking_date_and_separates_naps(tmp_path):
    con = source_database(tmp_path / "source.db")
    wake = int(datetime(2026, 9, 25, 5, tzinfo=timezone.utc).timestamp() * 1000)
    # Begins before switch; ends after switch. Garmin wins on the waking date.
    add_sleep(con, 1, wake - 8 * 3_600_000, wake, 1)
    add_sleep(con, 2, wake - 8 * 3_600_000, wake, 2)
    add_sleep(con, 3, wake + 4 * 3_600_000, wake + 5 * 3_600_000, 2)
    add_sleep(con, 4, wake - 32 * 3_600_000, wake - 24 * 3_600_000, 1, phases=False)
    con.commit()
    with patch.object(hc, "settings", config()):
        data = hc._read_sleep(con)
    assert {row["external_id"] for row in data["rows"]} == {"2", "3", "4"}
    main = next(row for row in data["rows"] if row["external_id"] == "2")
    assert main["day"] == date(2026, 9, 25)
    assert main["asleep_minutes"] == 240
    assert not next(row for row in data["rows"] if row["external_id"] == "3")["main_sleep"]
    assert next(row for row in data["rows"] if row["external_id"] == "4")["asleep_minutes"] is None
    con.close()


def test_sleep_import_retrofills_idempotently_and_preserves_missing_schema(tmp_path):
    path = tmp_path / "source.db"
    con = source_database(path)
    end = int(datetime(2026, 9, 26, 5, tzinfo=timezone.utc).timestamp() * 1000)
    add_sleep(con, 1, end - 8 * 3_600_000, end, 2, phases=False)
    con.commit()
    target = create_engine(f"sqlite:///{tmp_path / 'target.db'}")
    SQLModel.metadata.create_all(target)
    with patch.object(hc, "settings", config()), patch.object(hc, "engine", target):
        hc.import_health_connect(path)
        con.execute("INSERT INTO sleep_stages_table VALUES (?,?,?,2)", (1, end - 8 * 3_600_000, end))
        con.commit()
        hc.import_health_connect(path)
        hc.import_health_connect(path)
        with Session(target) as session:
            rows = session.exec(select(SleepSession)).all()
            assert len(rows) == 1
            assert rows[0].asleep_minutes == 480
        con.execute("DROP TABLE sleep_stages_table")
        con.commit()
        hc.import_health_connect(path, full=True)
        with Session(target) as session:
            assert session.exec(select(SleepSession)).one().asleep_minutes == 480
        con.execute("DROP TABLE sleep_session_record_table")
        con.commit()
        hc.import_health_connect(path, full=True)
        with Session(target) as session:
            assert session.exec(select(SleepSession)).one().asleep_minutes == 480
    con.close()
    target.dispose()


def test_sleep_elapsed_time_uses_utc_even_across_dst(tmp_path):
    con = source_database(tmp_path / "source.db")
    start = int(datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc).timestamp() * 1000)
    end = start + 3_600_000
    add_sleep(con, 1, start, end, 2)
    con.execute("UPDATE sleep_session_record_table SET end_zone_offset=3600")
    con.commit()
    with patch.object(hc, "settings", config()):
        row = hc._read_sleep(con)["rows"][0]
    assert row["started_at"] == row["ended_at"]
    assert row["duration_window_minutes"] == 60
    assert row["asleep_minutes"] == 30
    con.close()
