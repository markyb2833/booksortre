from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from flask import Flask

from .extensions import db
from .routes import main
from .schema import ensure_schema


def _configured_instance_path() -> str | None:
    return os.environ.get("BOOKSORT_INSTANCE_PATH") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")


def create_app(config: dict | None = None) -> Flask:
    instance_path = _configured_instance_path()
    if instance_path:
        app = Flask(__name__, instance_relative_config=True, instance_path=instance_path)
    else:
        app = Flask(__name__, instance_relative_config=True)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    default_db_path = Path(app.instance_path) / "booksort.db"
    app.config.from_mapping(
        SECRET_KEY="dev-change-me",
        BOOKSORT_PASSWORD=None,
        PERMANENT_SESSION_LIFETIME=timedelta(days=3650),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{default_db_path.as_posix()}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JSON_SORT_KEYS=False,
    )
    app.config.from_prefixed_env("BOOKSORT")
    app.config["BOOKSORT_PASSWORD"] = (
        os.environ.get("BOOKSORT_PASSWORD")
        or app.config.get("BOOKSORT_PASSWORD")
        or app.config.get("PASSWORD")
    )
    if os.environ.get("RAILWAY_ENVIRONMENT") and "BOOKSORT_SESSION_COOKIE_SECURE" not in os.environ:
        app.config["SESSION_COOKIE_SECURE"] = True

    database_url = os.environ.get("DATABASE_URL") or app.config.get("DATABASE_URL")
    if database_url:
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
        elif database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        app.config["SQLALCHEMY_DATABASE_URI"] = database_url

    if config:
        app.config.update(config)

    db.init_app(app)
    app.register_blueprint(main)

    with app.app_context():
        ensure_schema(db.engine)

    return app
