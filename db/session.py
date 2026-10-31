"""Database connection. Settings come from the .env file in the project root."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def _alembic_config(connection) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.attributes["connection"] = connection
    return config


def init_db() -> None:
    """Bring the database up to date by applying any pending migrations.

    A database created before migrations existed already has the original tables but no
    alembic_version table: it is marked ("stamped") as revision 0001, so only the newer
    migrations run and no existing data is touched.
    """
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        tables = inspect(conn).get_table_names()
        config = _alembic_config(conn)
        if "documents" in tables and "alembic_version" not in tables:
            command.stamp(config, "0001")
        command.upgrade(config, "head")


def reset_db() -> None:
    """Delete EVERY table and rebuild from migrations. Only for the test database."""
    if not DATABASE_URL.endswith("_test"):
        raise RuntimeError("reset_db() refuses to run on a database whose name does not end in _test")
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    init_db()


def get_session() -> Session:
    return SessionLocal()
