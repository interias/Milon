import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import SQLModel, Session, create_engine, select

from app.ingest import health_connect as hc
from app.models import BodyMeasurement


def test_weight_bounds_protect_incremental_and_full_import(tmp_path):
    source = tmp_path / "export.db"
    with sqlite3.connect(source) as con:
        con.executescript("""
            CREATE TABLE application_info_table(row_id, package_name);
            INSERT INTO application_info_table VALUES (1, 'scale');
            CREATE TABLE weight_record_table(time, zone_offset, weight, app_info_id);
            CREATE TABLE body_fat_record_table(time, zone_offset, percentage, app_info_id);
            CREATE TABLE distance_record_table(start_time, end_time, distance, app_info_id);
            CREATE TABLE exercise_session_record_table(uuid, start_time, start_zone_offset,
                end_time, exercise_type, app_info_id);
            CREATE TABLE vo2_max_record_table(time, zone_offset, vo2_milliliters_per_minute_kilogram);
            CREATE TABLE steps_record_table(local_date, count, app_info_id);
        """)
        weights = [73100, 14300, 8100, 73500, 50000, 110000, 111000, 0, None]
        con.executemany("INSERT INTO weight_record_table VALUES (?, 0, ?, 1)",
                        [(i * 1000, w) for i, w in enumerate(weights)])
        con.executemany("INSERT INTO body_fat_record_table VALUES (?, 0, 17, 1)",
                        [(i * 1000,) for i in range(len(weights) + 1)])
    con.close()
    config = SimpleNamespace(body_source_package="scale", steps_source_package="",
                             body_weight_min_kg=50, body_weight_max_kg=110)
    engine = create_engine(f"sqlite:///{tmp_path / 'target.db'}")
    SQLModel.metadata.create_all(engine)
    with patch.object(hc, "settings", config), patch.object(hc, "engine", engine):
        for full in (False, False, True):
            result = hc.import_health_connect(source, full=full)
            with Session(engine) as session:
                rows = session.exec(select(BodyMeasurement)).all()
                assert sorted(r.weight_kg for r in rows if r.weight_kg is not None) == [50, 73.1, 73.5, 110]
                # Standalone body fat is retained; rejected weights cannot leak paired body fat.
                assert len(rows) == 5
            assert result["skipped_body"] == 5
    engine.dispose()
