"""The hand-written Alembic migration must stay in lockstep with the ORM models.

Builds the schema two ways on SQLite — by running the migration and by
`Base.metadata.create_all` — and asserts the tables and columns match, so a model
change that forgets a matching migration (or vice versa) fails CI instead of drifting
silently into a broken production deploy.
"""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, create_engine, inspect

from argus.db import models  # noqa: F401  (register tables on Base.metadata)
from argus.db.base import Base

_VERSIONS_DIR = Path(__file__).resolve().parent.parent / "migrations" / "versions"


def _migration_files() -> list[Path]:
    """Every migration, in filename order (the 000N_ prefix is the chain order)."""
    files = sorted(p for p in _VERSIONS_DIR.glob("*.py") if not p.name.startswith("__"))
    assert files, "no migrations found"
    return files


def _schema(engine: Engine) -> dict[str, dict[str, bool]]:
    """{table: {column: nullable}} for every table except alembic's bookkeeping."""
    insp = inspect(engine)
    return {
        table: {col["name"]: bool(col["nullable"]) for col in insp.get_columns(table)}
        for table in insp.get_table_names()
        if table != "alembic_version"
    }


def _run_migrations(url: str) -> None:
    engine = create_engine(url)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):  # binds the global `op` the migrations use
            for path in _migration_files():
                spec = importlib.util.spec_from_file_location(f"mig_{path.stem}", path)
                assert spec is not None and spec.loader is not None
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.upgrade()
        conn.commit()


def test_migration_schema_matches_models(tmp_path: Path) -> None:
    # File-based SQLite so the schema survives across connections (in-memory would not).
    migration_url = f"sqlite:///{tmp_path / 'migration.db'}"
    _run_migrations(migration_url)
    migration_schema = _schema(create_engine(migration_url))

    model_url = f"sqlite:///{tmp_path / 'models.db'}"
    Base.metadata.create_all(create_engine(model_url))
    model_schema = _schema(create_engine(model_url))

    assert migration_schema == model_schema
