import sqlite3
from datetime import date

import pytest

from app.metrics.run_references import observed_hr_reference


@pytest.fixture
def raw(tmp_path):
    path = tmp_path / "raw.db"
    with sqlite3.connect(path) as con:
        con.executescript("""
            CREATE TABLE application_info_table(row_id,package_name);
            INSERT INTO application_info_table VALUES(1,'watch'),(2,'mirror');
            CREATE TABLE exercise_session_record_table(uuid,start_time,end_time,exercise_type,app_info_id);
            CREATE TABLE heart_rate_record_table(row_id,app_info_id);
            INSERT INTO heart_rate_record_table VALUES(1,1),(2,2);
            CREATE TABLE heart_rate_record_series_table(parent_key,epoch_millis,beats_per_minute);
        """)
    return path


def add(path, day, bpm, *, source=1, step=1, duplicate=False):
    start = day * 86400000
    with sqlite3.connect(path) as con:
        con.execute("INSERT INTO exercise_session_record_table VALUES(?,?,?,?,?)",
                    (f"{day}-{source}", start, start + 120000, 33, source))
        values = [(source, start + t * 1000, bpm(t) if callable(bpm) else bpm)
                  for t in range(0, 121, step)]
        con.executemany("INSERT INTO heart_rate_record_series_table VALUES(?,?,?)", values)
        if duplicate:
            con.executemany("INSERT INTO heart_rate_record_series_table VALUES(?,?,?)", values)


def test_corroborated_lower_level_and_strict_provenance(raw):
    add(raw, 1, 184, duplicate=True)
    add(raw, 2, 182)
    add(raw, 3, 220, source=2)
    add(raw, 4, 195)  # Uncorroborated high day does not determine reference.
    result = observed_hr_reference(raw, "watch")
    assert result["status"] == "candidate"
    assert result["candidate_bpm"] == 182
    assert result["qualifying_days"] == 3
    assert len(result["evidence"]) == 2
    assert {r["session_id"] for r in result["evidence"]} == {"1-1", "2-1"}
    assert result["source_package"] == "watch"


def test_duplicate_session_same_day_is_not_corroboration(raw):
    add(raw, 1, 184)
    with sqlite3.connect(raw) as con:
        con.execute("INSERT INTO exercise_session_record_table SELECT * FROM exercise_session_record_table")
    result = observed_hr_reference(raw, "watch")
    assert result["candidate_bpm"] is None
    assert result["qualifying_days"] == 1


@pytest.mark.parametrize("bpm,step", [(lambda t: 210 if t == 60 else 130, 1),
                                       (180, 10), (lambda t: 0 if t % 30 == 0 else 185, 1),
                                       (lambda t: 185 if t % 2 else 160, 1)])
def test_spikes_sparse_invalid_and_jumping_series_do_not_qualify(raw, bpm, step):
    add(raw, 1, bpm, step=step)
    add(raw, 2, bpm, step=step)
    result = observed_hr_reference(raw, "watch")
    assert result["status"] == "insufficient_data"
    assert result["candidate_bpm"] is None


def test_future_days_do_not_corroborate(raw):
    add(raw, 1, 182)
    add(raw, 2, 184)
    result = observed_hr_reference(raw, "watch", today=date(1970, 1, 2))
    assert result["candidate_bpm"] is None
    assert result["qualifying_days"] == 1


def test_missing_source_does_not_create_file(tmp_path, raw):
    absent = tmp_path / "absent.db"
    assert observed_hr_reference(absent, "watch")["status"] == "unavailable"
    assert not absent.exists()
    assert observed_hr_reference(raw, "missing")["reason"] == "source_package_missing"
