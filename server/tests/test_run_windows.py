import sqlite3

import pytest

from app.ingest.run_windows import read_run_windows


@pytest.fixture
def source():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE application_info_table(row_id,package_name);
        INSERT INTO application_info_table VALUES (1,'watch'),(2,'strava');
        CREATE TABLE exercise_session_record_table(uuid,start_time,end_time,exercise_type,app_info_id);
        INSERT INTO exercise_session_record_table VALUES (X'ABCD',0,120500,33,1),('mirror',0,120500,33,2);
        CREATE TABLE SpeedRecordTable(row_id,app_info_id);
        INSERT INTO SpeedRecordTable VALUES (10,1),(20,2);
        CREATE TABLE speed_record_table(parent_key,epoch_millis,speed);
        CREATE TABLE heart_rate_record_table(row_id,app_info_id);
        INSERT INTO heart_rate_record_table VALUES (10,1),(20,2);
        CREATE TABLE heart_rate_record_series_table(parent_key,epoch_millis,beats_per_minute);
    """)
    for parent, speed, hr in ((10, 3, 150), (20, 6, 80)):
        con.executemany("INSERT INTO speed_record_table VALUES (?,?,?)",
                        [(parent, t * 1000, speed) for t in range(121)])
        con.executemany("INSERT INTO heart_rate_record_series_table VALUES (?,?,?)",
                        [(parent, t * 1000, hr) for t in range(121)])
    yield con
    con.close()


def extract(con, ids=("abcd", "mirror")):
    return read_run_windows(con, [{"external_id": id, "exercise_type": 33} for id in ids], "watch")


def test_strict_source_complete_bins_and_binary_uuid(source):
    result = extract(source)
    assert result["available"]
    assert result["session_ids"] == ["abcd"]
    assert [r["minute"] for r in result["rows"]] == [0.5, 1.5]
    for row in result["rows"]:
        assert row["speed_m_min"] == 180
        assert row["hr_bpm"] == 150
        assert row["coverage"] == 1
        assert row["steady"] is True
        assert row["model_version"] == "shr-v1"


def test_invalid_samples_remain_gaps_and_joint_coverage(source):
    source.execute("UPDATE speed_record_table SET speed=99 WHERE parent_key=10 AND epoch_millis=30000")
    source.execute("UPDATE heart_rate_record_series_table SET beats_per_minute=0 "
                   "WHERE parent_key=10 AND epoch_millis=40000")
    row = extract(source)["rows"][0]
    assert row["coverage"] == pytest.approx(56 / 60)
    assert row["speed_m_min"] == 180
    assert row["hr_bpm"] == 150
    assert row["steady"]


def test_large_gaps_are_not_interpolated(source):
    source.execute("DELETE FROM speed_record_table WHERE parent_key=10 AND epoch_millis BETWEEN 10000 AND 29000")
    row = extract(source)["rows"][0]
    assert row["coverage"] == pytest.approx(39 / 60)
    assert not row["steady"]


def test_duplicate_samples_use_median_and_do_not_inflate_coverage(source):
    source.executemany("INSERT INTO speed_record_table VALUES (10,?,?)",
                        [(t * 1000, s) for t in range(121) for s in (4, 10)])
    row = extract(source)["rows"][0]
    assert row["speed_m_min"] == 240
    assert row["coverage"] == 1


def test_samples_outside_session_never_fill_edges(source):
    source.execute("DELETE FROM speed_record_table WHERE parent_key=10 AND epoch_millis < 10000")
    source.execute("INSERT INTO speed_record_table VALUES (10,-1000,3)")
    row = extract(source)["rows"][0]
    assert row["coverage"] == pytest.approx(50 / 60)
    assert not row["steady"]


@pytest.mark.parametrize("mutation", [
    "DROP TABLE SpeedRecordTable",
    "DROP TABLE heart_rate_record_series_table",
    "ALTER TABLE speed_record_table RENAME COLUMN speed TO other",
    "DELETE FROM speed_record_table WHERE parent_key=10",
    "DELETE FROM heart_rate_record_series_table WHERE parent_key=10",
    "DELETE FROM application_info_table WHERE row_id=1",
])
def test_missing_schema_or_source_preserves_existing_windows(source, mutation):
    source.execute(mutation)
    assert extract(source) == {"rows": [], "session_ids": [], "available": False}


def test_invalid_but_represented_series_replaces_old_windows(source):
    source.execute("UPDATE speed_record_table SET speed=NULL WHERE parent_key=10")
    result = extract(source)
    assert result["session_ids"] == ["abcd"]
    assert all(r["speed_m_min"] is None and r["hr_bpm"] is None and r["coverage"] == 0
               and not r["steady"] for r in result["rows"])


def test_partial_export_only_replaces_represented_session(source):
    source.execute("INSERT INTO exercise_session_record_table VALUES ('missing',200000,320000,33,1)")
    assert extract(source, ("abcd", "missing"))["session_ids"] == ["abcd"]


def test_short_complete_source_can_clear_previous_windows(source):
    source.execute("UPDATE exercise_session_record_table SET end_time=59000 WHERE app_info_id=1")
    assert extract(source) == {"rows": [], "session_ids": ["abcd"], "available": True}


def test_empty_config_and_nonrunning_inputs_do_not_fall_back(source):
    assert not read_run_windows(source, [{"external_id": "abcd", "exercise_type": 33}], "")["available"]
    assert not read_run_windows(source, [{"external_id": "abcd", "exercise_type": 58}], "watch")["available"]


def test_corrupt_session_duration_is_ignored(source):
    source.execute("UPDATE exercise_session_record_table SET end_time=1e30")
    assert not extract(source)["available"]
