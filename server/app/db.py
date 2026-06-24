"""DB-Engine, Schema-Erstellung, Session-Dependency."""
from collections.abc import Iterator

from sqlalchemy import func
from sqlalchemy import select as _select
from sqlalchemy.dialects.sqlite import insert as _sqlite_insert
from sqlmodel import Session, SQLModel, create_engine

from . import models  # noqa: F401  -- registriert die Tabellen-Metadaten
from .config import settings

engine = create_engine(
    settings.resolved_database_url(),
    echo=False,
    connect_args={"check_same_thread": False},  # SQLite + FastAPI
)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _run_migrations()


def _run_migrations() -> None:
    """Leichte, idempotente Spalten-Migrationen fuer bereits bestehende DBs."""
    with engine.begin() as con:
        def cols(table: str) -> set[str]:
            return {row[1] for row in con.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()}

        cr = cols("coach_reports")
        if "prompt" not in cr:
            con.exec_driver_sql("ALTER TABLE coach_reports ADD COLUMN prompt TEXT")
        for col, typ in (("prompt_tokens", "INTEGER"), ("completion_tokens", "INTEGER"), ("cost_usd", "REAL")):
            if col not in cr:
                con.exec_driver_sql(f"ALTER TABLE coach_reports ADD COLUMN {col} {typ}")
        sync_cols = cols("sync_state")
        if "status" not in sync_cols:
            con.exec_driver_sql("ALTER TABLE sync_state ADD COLUMN status TEXT")
        if "detail" not in sync_cols:
            con.exec_driver_sql("ALTER TABLE sync_state ADD COLUMN detail TEXT")


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def count_rows(session: Session, model, source: str | None = None) -> int:
    q = _select(func.count()).select_from(model)
    if source is not None:
        q = q.where(model.source == source)
    return int(session.execute(q).scalar_one())


def upsert(session: Session, model, rows: list[dict], conflict_cols: list[str],
           update_cols: list[str] | None = None, chunk: int = 400) -> None:
    """Idempotentes Einfuegen via SQLite ON CONFLICT.
    - update_cols=None  -> DO NOTHING (Append: nur neue Zeilen werden geschrieben)
    - update_cols=[...]  -> DO UPDATE der genannten Spalten (z. B. Schritte/Tag)."""
    for i in range(0, len(rows), chunk):
        batch = rows[i:i + chunk]
        if not batch:
            continue
        stmt = _sqlite_insert(model).values(batch)
        if update_cols:
            stmt = stmt.on_conflict_do_update(
                index_elements=conflict_cols,
                set_={c: getattr(stmt.excluded, c) for c in update_cols},
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=conflict_cols)
        session.execute(stmt)
