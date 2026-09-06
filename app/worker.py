from __future__ import annotations

import logging
import time

from apscheduler.schedulers.blocking import BlockingScheduler

from .bootstrap import migration_is_current
from .database import build_engine, build_session_factory
from .services import create_refresh_run, run_refresh
from .settings import load_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("bma-briefing-worker")


def main() -> None:
    settings = load_settings()
    for _ in range(60):
        if migration_is_current(settings):
            break
        LOG.info("Waiting for the application to migrate the database")
        time.sleep(5)
    else:
        raise RuntimeError("Database migration did not become ready")
    settings.export_root.mkdir(parents=True, exist_ok=True)
    engine = build_engine(settings.db_path)
    factory = build_session_factory(engine)

    def scheduled_refresh() -> None:
        run_id = create_refresh_run(factory, "scheduled", None)
        run_refresh(factory, run_id)

    scheduler = BlockingScheduler(timezone=settings.refresh_timezone)
    scheduler.add_job(scheduled_refresh, "cron", hour=settings.refresh_hour,
                      minute=settings.refresh_minute, max_instances=1, coalesce=True,
                      misfire_grace_time=3600)
    try:
        scheduler.start()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
