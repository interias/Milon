from datetime import date, datetime
import json
import sqlite3
from types import SimpleNamespace

from sqlmodel import Session, SQLModel, create_engine, select

from app.ingest import watch_switch as repair
from app.models import ExerciseSession, RunBestEffort, RunFitnessReference, RunMinute, StepsDaily


def test_repair_preserves_history_and_transition_day_and_is_repeatable(tmp_path, monkeypatch):
    db = tmp_path / "tracker.db"
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    SQLModel.metadata.create_all(engine)
    export = tmp_path / "health_connect_export.db"
    with sqlite3.connect(export) as raw:
        raw.execute("CREATE TABLE application_info_table(package_name)")
        raw.execute("INSERT INTO application_info_table VALUES ('new')")
    with Session(engine) as session:
        session.add(RunFitnessReference(created_at=datetime(2026, 1, 1), payload=json.dumps({
            "max_hr": 180, "sensor_changes": []})))
        for day in (24, 25, 26, 27):
            session.add(StepsDaily(day=date(2026, 9, day), steps=100, source="health_connect"))
            session.add(ExerciseSession(external_id="new-26" if day == 26 else f"old-{day}", started_at=datetime(2026, 9, day),
                                        exercise_type=33, source="health_connect"))
        session.add(RunMinute(external_id="new-26", minute=10.5, speed_m_min=160,
                              hr_bpm=140, coverage=1, steady=True))
        session.add(RunBestEffort(external_id="new-26", distance_m=1000, seconds=360,
                                  started_at=datetime(2026, 9, 26)))
        session.commit()
    monkeypatch.setattr(repair, "DATA_DIR", tmp_path)
    monkeypatch.setattr(repair, "INCOMING_DIR", tmp_path)
    monkeypatch.setattr(repair, "engine", engine)
    config = SimpleNamespace(resolved_database_url=lambda: f"sqlite:///{db.as_posix()}",
                             watch_source_switch_date=None, watch_source_package="", watch_source_legacy_session_ids=[])
    monkeypatch.setattr(repair, "settings", config)
    saved_env = []
    monkeypatch.setattr(repair, "update_env_file", lambda updates: saved_env.append(updates))
    monkeypatch.setattr(repair, "read_health_connect", lambda _: {
        "steps": [dict(day=date(2026, 9, d), steps=200, source="health_connect") for d in (25, 26)],
        "sessions": [dict(external_id="new-26", started_at=datetime(2026, 9, 26),
                          exercise_type=33, avg_hr=150, source="health_connect")],
        "resting": [], "best_efforts": [], "run_windows": {"rows": []}})
    for _ in range(2):
        result = repair.repair(date(2026, 9, 25), date(2026, 9, 26), "new", sessions_since=date(2026, 9, 26))
        assert result["sessions_after"] == 1
    with Session(engine) as session:
        assert {r.external_id for r in session.exec(select(ExerciseSession)).all()} == {
            "old-24", "old-25", "new-26", "old-27"}
        assert {r.day.day: r.steps for r in session.exec(select(StepsDaily)).all()} == {24: 100, 25: 200, 26: 200, 27: 100}
        refs = session.exec(select(RunFitnessReference).order_by(RunFitnessReference.id)).all()
        assert len(refs) == 2
        assert json.loads(refs[-1].payload)["max_hr"] == 180
        assert len(session.exec(select(RunMinute)).all()) == 1
        assert len(session.exec(select(RunBestEffort)).all()) == 1
    assert config.watch_source_switch_date is None
    assert len(list((tmp_path / "backups").glob("*.db"))) == 2
    assert saved_env[-1]["WATCH_SOURCE_SWITCH_DATE"] == "2026-09-25"
    engine.dispose()
