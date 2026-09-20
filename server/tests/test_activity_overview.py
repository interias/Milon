from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.api import metrics
from app.metrics import activity, running
from app.models import ExerciseSession, StepsDaily, Workout, WorkoutSet


@pytest.fixture
def activity_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'activity.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(activity, "engine", engine)
    monkeypatch.setattr(running, "engine", engine)
    monkeypatch.setattr(activity.settings, "timezone", "Europe/Berlin")
    yield engine
    engine.dispose()


def add_run(session, started, km=5):
    session.add(ExerciseSession(exercise_type=33, started_at=started,
                               ended_at=started + timedelta(minutes=km * 6), distance_km=km))


def test_calendar_boundaries_local_year_and_future_rows(activity_db):
    # Jan 1 in Berlin, still Dec 31 in UTC. Current window starts Dec 26.
    now = datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc)
    with Session(activity_db) as session:
        for started in [datetime(2026, 12, 18, 23, 59), datetime(2026, 12, 19),
                        datetime(2026, 12, 25, 23, 59), datetime(2026, 12, 26),
                        datetime(2027, 1, 1, 0, 1), datetime(2027, 1, 1, 1), datetime(2027, 1, 2)]:
            add_run(session, started)
            session.add(Workout(started_at=started, source="hevy"))
        add_run(session, datetime(2026, 12, 29), km=0.2)  # rejected by accepted-run filter
        session.add(Workout(started_at=datetime(2026, 12, 29), source="other"))
        session.add(Workout(started_at=None))
        session.commit()
    result = activity.overview(now)
    assert result["from_date"] == "2026-12-26"
    assert result["to_date"] == "2027-01-01"
    assert result["previous_from_date"] == "2026-12-19"
    assert result["previous_to_date"] == "2026-12-25"
    assert result["running"] == {"current_km": 10.0, "previous_km": 10.0}
    assert result["strength"] == {"current_sessions": 2, "previous_sessions": 2}


def test_sparse_steps_are_not_zero_filled_and_sets_do_not_inflate_sessions(activity_db):
    with Session(activity_db) as session:
        session.add_all([StepsDaily(day=date(2026, 9, 19), steps=1000),
                         StepsDaily(day=date(2026, 9, 20), steps=0),
                         StepsDaily(day=date(2026, 9, 13), steps=2000),
                         StepsDaily(day=date(2026, 9, 6), steps=9000),
                         StepsDaily(day=date(2026, 9, 21), steps=9000)])
        workout = Workout(started_at=datetime(2026, 9, 19, 10))
        session.add(workout)
        session.flush()
        session.add_all([WorkoutSet(workout_id=workout.id, exercise="Squat", set_index=i) for i in range(10)])
        session.commit()
    result = activity.overview(datetime(2026, 9, 20, 12, tzinfo=timezone.utc))
    assert result["strength"] == {"current_sessions": 1, "previous_sessions": 0}
    assert result["steps"] == {"current_avg": 500.0, "previous_avg": 2000.0,
                               "current_days": 2, "previous_days": 1}


def test_empty_activity_and_api_contract(activity_db):
    app = FastAPI()
    app.include_router(metrics.router)
    with TestClient(app) as client:
        response = client.get("/metrics/activity/overview")
    assert response.status_code == 200
    result = response.json()
    assert result["running"] == {"current_km": 0.0, "previous_km": 0.0}
    assert result["strength"] == {"current_sessions": 0, "previous_sessions": 0}
    assert result["steps"] == {"current_avg": None, "previous_avg": None,
                               "current_days": 0, "previous_days": 0}
