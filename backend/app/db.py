import os
from pathlib import Path

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "tracker.db"


def make_engine(url: str | None = None):
    if url is None:
        path = Path(os.environ.get("TRACKER_DB", DEFAULT_DB))
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{path}"
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


engine = make_engine()


def init_db(eng=None) -> None:
    from . import models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(eng or engine)


def get_session():
    with Session(engine) as session:
        yield session
