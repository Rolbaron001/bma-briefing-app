from __future__ import annotations

import sqlite3

from docx import Document

from app.bootstrap import initialise, migration_is_current
from app.models import Assessment, BriefRun
from app.services import create_archive_export, create_assessment_export, create_refresh_run, run_refresh


def test_startup_is_idempotent_and_preserves_roles(settings):
    engine, factory = initialise(settings)
    with factory.begin() as db:
        row = db.query(__import__("app.models", fromlist=["AppUser"]).AppUser).filter_by(email="admin@example.org").one()
        row.role = "viewer"
    engine.dispose()
    engine, factory = initialise(settings)
    try:
        assert migration_is_current(settings)
        with factory() as db:
            row = db.query(__import__("app.models", fromlist=["AppUser"]).AppUser).filter_by(email="admin@example.org").one()
            assert row.role == "viewer"
        cx = sqlite3.connect(settings.db_path)
        assert cx.execute("PRAGMA journal_mode").fetchone()[0].casefold() == "wal"
        cx.close()
    finally:
        engine.dispose()


def test_docx_and_archive_exports_use_persistent_files(settings):
    engine, factory = initialise(settings)
    try:
        with factory.begin() as db:
            assessment = Assessment(product_type="Threat Assessment", query="Test", result="BLUF\n\nResult",
                                    model="test", created_by=1)
            db.add(assessment); db.flush(); assessment_id = assessment.id
        docx = create_assessment_export(settings, factory, assessment_id, 1)
        path = settings.export_root / docx.storage_name
        assert path.is_file() and Document(path).paragraphs[0].text == "Threat Assessment"
        archive = create_archive_export(settings, factory, 1, "markdown")
        assert (settings.export_root / archive.storage_name).read_text(encoding="utf-8").startswith("# NBTC Brief archive")
    finally:
        engine.dispose()


def test_total_refresh_failure_preserves_last_success(settings, monkeypatch):
    engine, factory = initialise(settings)
    try:
        with factory.begin() as db:
            prior = BriefRun(trigger="manual", status="succeeded")
            db.add(prior); db.flush(); prior_id = prior.id
        monkeypatch.setattr("app.services.build_brief", lambda _interests: (_ for _ in ()).throw(RuntimeError("offline")))
        run_id = create_refresh_run(factory, "manual", 1)
        run_refresh(factory, run_id)
        with factory() as db:
            assert db.get(BriefRun, run_id).status == "failed"
            assert db.get(BriefRun, prior_id).status == "succeeded"
    finally:
        engine.dispose()
