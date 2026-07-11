from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from argus.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):  # type: ignore[no-untyped-def]
    return create_engine(url or get_settings().database_url, pool_pre_ping=True)


_session_factory: sessionmaker[Session] | None = None


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=make_engine(), expire_on_commit=False)
    return _session_factory


def init_sqlite_schema() -> None:
    """Create the schema directly for a SQLite database — no Alembic, no migration step.

    A free single-container deployment can run on a SQLite file (no Postgres server), and
    SQLite doesn't share Postgres's JSONB migrations. On a Postgres deployment this is a
    no-op (migrations own the schema). Idempotent: create_all only creates missing tables.
    """
    engine = make_engine()
    if engine.dialect.name != "sqlite":
        return
    from argus.db import models  # noqa: F401 — register the mappers on Base.metadata

    Base.metadata.create_all(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
