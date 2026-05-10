from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .extensions import db


def ensure_schema(engine: Engine) -> None:
    db.create_all()

    inspector = inspect(engine)
    if "book" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("book")}
    dialect = engine.dialect.name

    migrations = []
    if "archived" not in columns:
        if dialect == "sqlite":
            migrations.append("ALTER TABLE book ADD COLUMN archived BOOLEAN NOT NULL DEFAULT 0")
        else:
            migrations.append("ALTER TABLE book ADD COLUMN archived BOOLEAN NOT NULL DEFAULT FALSE")
    if "archived_at" not in columns:
        if dialect == "postgresql":
            migrations.append("ALTER TABLE book ADD COLUMN archived_at TIMESTAMP")
        else:
            migrations.append("ALTER TABLE book ADD COLUMN archived_at DATETIME")

    if not migrations:
        return

    with engine.begin() as connection:
        for migration in migrations:
            connection.execute(text(migration))
