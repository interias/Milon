import sqlite3

import numpy as np
import pytest

from app.ingest.run_windows import GARMIN_PACKAGE, _cadence_gap_limit, _interpolate, read_run_windows


def source(cadence_seconds, package=GARMIN_PACKAGE):
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE application_info_table(row_id,package_name);
        CREATE TABLE exercise_session_record_table(uuid,start_time,end_time,exercise_type,app_info_id);
        INSERT INTO exercise_session_record_table VALUES ('run',0,600001,33,1);
        CREATE TABLE SpeedRecordTable(row_id,app_info_id);
        INSERT INTO SpeedRecordTable VALUES (1,1);
        CREATE TABLE speed_record_table(parent_key,epoch_millis,speed);
        CREATE TABLE heart_rate_record_table(row_id,app_info_id);
        INSERT INTO heart_rate_record_table VALUES (1,1);
        CREATE TABLE heart_rate_record_series_table(parent_key,epoch_millis,beats_per_minute);
    """)
    con.execute("INSERT INTO application_info_table VALUES (1,?)", (package,))
    samples = [(1, timestamp, 3) for timestamp in range(0, 600001, cadence_seconds * 1000)]
    con.executemany("INSERT INTO speed_record_table VALUES (?,?,?)", samples)
    con.executemany("INSERT INTO heart_rate_record_series_table VALUES (?,?,?)",
                    [(parent, timestamp, 145) for parent, timestamp, _ in samples])
    return con


def extract(con, package=GARMIN_PACKAGE):
    return read_run_windows(con, [{"external_id": "run", "exercise_type": 33}], package)


@pytest.mark.parametrize("cadence", [16, 26])
def test_regular_garmin_cadence_has_measured_coverage(cadence):
    con = source(cadence)
    try:
        result = extract(con)
        assert result["session_ids"] == ["run"]
        assert all(row["coverage"] == 1 and row["steady"] for row in result["rows"][1:-1])
        assert all(row["speed_m_min"] == 180 and row["hr_bpm"] == 145 for row in result["rows"])
    finally:
        con.close()


def test_missing_garmin_sample_leaves_a_52_second_gap():
    con = source(26)
    try:
        con.execute("DELETE FROM speed_record_table WHERE epoch_millis=260000")
        # Typical cadence remains 26 s; missing sample creates 234..286 s gap >39 s.
        result = extract(con)
        assert result["rows"][3]["coverage"] == pytest.approx(54 / 60)
        assert result["rows"][4]["coverage"] == pytest.approx(14 / 60)
        assert not result["rows"][4]["steady"]
    finally:
        con.close()


def test_invalid_sample_does_not_get_interpolated_across_regular_cadence():
    con = source(26)
    try:
        con.execute("UPDATE heart_rate_record_series_table SET beats_per_minute=0 WHERE epoch_millis=260000")
        result = extract(con)
        assert result["rows"][4]["coverage"] == pytest.approx(14 / 60)
        assert not result["rows"][4]["steady"]
    finally:
        con.close()


def test_extra_dense_hr_samples_do_not_disqualify_regular_coarse_cadence():
    con = source(26)
    try:
        # The real Garmin export includes additional HR samples between otherwise
        # regular 26 s measurements. Extra measurements are not sensor gaps.
        con.executemany("INSERT INTO heart_rate_record_series_table VALUES (1,?,145)",
                        [(26000 * index + 13000,) for index in range(7)])
        result = extract(con)
        assert all(row["coverage"] == 1 and row["steady"] for row in result["rows"][1:-1])
        con.execute("DELETE FROM heart_rate_record_series_table WHERE epoch_millis=260000")
        assert extract(con)["rows"][4]["coverage"] == pytest.approx(14 / 60)
    finally:
        con.close()


def test_samsung_and_fast_garmin_streams_keep_original_gap_rule():
    package = "com.sec.android.app.shealth"
    con = source(26, package)
    try:
        result = extract(con, package)
        assert all(row["coverage"] == 0 and not row["steady"] for row in result["rows"])
    finally:
        con.close()
    assert _cadence_gap_limit(np.arange(20) * 14000, GARMIN_PACKAGE) == 15000
    assert _cadence_gap_limit(np.arange(20) * 16000, package) == 15000


def test_irregular_sparse_and_short_garmin_streams_do_not_gain_coverage():
    irregular = np.cumsum([0, 16000, 4000, 26000, 50000, 10000, 20000, 15000, 35000])
    assert _cadence_gap_limit(irregular, GARMIN_PACKAGE) == 15000
    assert _cadence_gap_limit(np.arange(20) * 60000, GARMIN_PACKAGE) == 15000
    assert _cadence_gap_limit(np.arange(5) * 26000, GARMIN_PACKAGE) == 15000
    assert _cadence_gap_limit(np.arange(6) * 26000, GARMIN_PACKAGE) == 39000
    # Edge extrapolation and invalid values remain prohibited with the adapter enabled.
    values = np.full(6, 3.0)
    values[2] = np.nan
    interpolated = _interpolate(np.arange(6) * 26000, values,
                                np.array([-1, 39000, 65000, 150000]), 39000)
    assert np.isnan(interpolated).all()


def test_cadence_is_selected_per_stream_and_per_session():
    con = source(16)
    try:
        con.execute("DELETE FROM heart_rate_record_series_table")
        con.executemany("INSERT INTO heart_rate_record_series_table VALUES (1,?,145)",
                        [(timestamp,) for timestamp in range(0, 600001, 60000)])
        result = extract(con)
        assert all(row["coverage"] == 0 for row in result["rows"])
        # Dense speed alone must not turn a sparse HR stream into measured minute coverage.
        con.execute("INSERT INTO exercise_session_record_table VALUES ('short',700000,760001,33,1)")
        con.executemany("INSERT INTO speed_record_table VALUES (1,?,3)", [(700000 + i * 16000,) for i in range(4)])
        con.executemany("INSERT INTO heart_rate_record_series_table VALUES (1,?,145)", [(700000 + i * 16000,) for i in range(4)])
        rows = read_run_windows(con, [{"external_id": name, "exercise_type": 33} for name in ("run", "short")], GARMIN_PACKAGE)["rows"]
        assert next(row for row in rows if row["external_id"] == "short")["coverage"] == 0
    finally:
        con.close()
