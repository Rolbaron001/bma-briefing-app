from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import select, update

from .database import build_engine, build_session_factory
from .models import AppUser, BriefRun, RefreshLock, utc_now
from .settings import Settings

ROLES = {"viewer", "analyst", "admin"}


def alembic_config(settings: Settings) -> Config:
    config = Config(str(settings.app_root / "alembic.ini"))
    config.set_main_option("script_location", str(settings.app_root / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{settings.db_path}")
    return config


def migration_is_current(settings: Settings) -> bool:
    if not settings.db_path.exists():
        return False
    engine = build_engine(settings.db_path)
    try:
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
        expected = ScriptDirectory.from_config(alembic_config(settings)).get_current_head()
        return bool(current and current == expected)
    finally:
        engine.dispose()


def initialise(settings: Settings):
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.export_root.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(settings), "head")
    engine = build_engine(settings.db_path)
    factory = build_session_factory(engine)
    with factory.begin() as db:
        for item in settings.bootstrap_users:
            email = item["email"].strip().casefold()
            role = item["role"].strip().lower()
            if role not in ROLES:
                raise RuntimeError(f"Invalid bootstrap role for {email}: {role}")
            if not db.scalar(select(AppUser).where(AppUser.email == email)):
                db.add(AppUser(email=email, role=role))
        if not db.get(RefreshLock, 1):
            db.add(RefreshLock(id=1))
        db.execute(update(BriefRun).where(BriefRun.status.in_(["queued", "running"])).values(
            status="interrupted", completed_at=utc_now(), error_message="Application restarted before completion"
        ))
        lock = db.get(RefreshLock, 1)
        if lock:
            lock.owner_token = None
            lock.run_id = None
            lock.acquired_at = None
    return engine, factory

