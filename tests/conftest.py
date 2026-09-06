from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_root=Path(__file__).resolve().parents[1],
        db_path=tmp_path / "db" / "briefing.db",
        export_root=tmp_path / "exports",
        public_url="http://localhost:8770",
        session_secret="test-session-secret-that-is-long-enough",
        bootstrap_users=[{"email": "admin@example.org", "role": "admin"},
                         {"email": "viewer@example.org", "role": "viewer"}],
        ai_enabled=False,
        anthropic_api_key=None,
        anthropic_model="test-model",
        development_email="admin@example.org",
        refresh_timezone="Africa/Johannesburg",
        refresh_hour=6,
        refresh_minute=0,
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def client(settings: Settings, monkeypatch):
    monkeypatch.setenv("BMA_BRIEFING_DEVELOPMENT_AUTH", "true")
    with TestClient(create_app(settings), base_url="http://localhost:8770") as value:
        yield value


@pytest.fixture
def admin_client(client: TestClient):
    response = client.get("/auth/development", follow_redirects=False)
    assert response.status_code == 303
    me = client.get("/api/me")
    assert me.status_code == 200
    client.headers["X-CSRF-Token"] = me.json()["csrf"]
    return client
