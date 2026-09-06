from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _bootstrap_users() -> list[dict[str, str]]:
    raw = os.environ.get("BMA_BRIEFING_BOOTSTRAP_USERS")
    if not raw:
        return [
            {"email": "barry@ubiquitech.co.za", "role": "admin"},
            {"email": "rolbaron001@gmail.com", "role": "admin"},
            {"email": "christo.bezuidenhout@bma.gov.za", "role": "admin"},
        ]
    try:
        values = json.loads(raw)
        return [
            {"email": str(value["email"]).strip().casefold(), "role": str(value.get("role", "viewer"))}
            for value in values
        ]
    except (ValueError, TypeError, KeyError) as exc:
        raise RuntimeError("BMA_BRIEFING_BOOTSTRAP_USERS must be a JSON list") from exc


@dataclass(frozen=True)
class Settings:
    app_root: Path
    db_path: Path
    export_root: Path
    public_url: str
    session_secret: str
    bootstrap_users: list[dict[str, str]]
    ai_enabled: bool
    anthropic_api_key: str | None
    anthropic_model: str
    development_email: str
    refresh_timezone: str
    refresh_hour: int
    refresh_minute: int
    build_version: str = "development"
    max_json_bytes: int = 5 * 1024 * 1024

    @property
    def secure_cookies(self) -> bool:
        return urlparse(self.public_url).scheme == "https"

    @property
    def allowed_hosts(self) -> list[str]:
        host = urlparse(self.public_url).hostname
        return [value for value in (host, "localhost", "127.0.0.1", "testserver") if value]

    @property
    def development_auth_enabled(self) -> bool:
        host = urlparse(self.public_url).hostname
        return _bool("BMA_BRIEFING_DEVELOPMENT_AUTH") and host in {"localhost", "127.0.0.1", "testserver"}


def load_settings() -> Settings:
    root = Path(os.environ.get("BMA_BRIEFING_APP_ROOT", Path(__file__).resolve().parents[1])).resolve()
    public_url = os.environ.get("BMA_BRIEFING_PUBLIC_URL", "http://localhost:8770").rstrip("/")
    secret = os.environ.get("BMA_BRIEFING_SESSION_SECRET")
    if not secret:
        if urlparse(public_url).hostname in {"localhost", "127.0.0.1", "testserver"}:
            secret = secrets.token_urlsafe(48)
        else:
            raise RuntimeError("BMA_BRIEFING_SESSION_SECRET is required")
    return Settings(
        app_root=root,
        db_path=Path(os.environ.get("BMA_BRIEFING_DB_PATH", root / "data" / "bma-briefing.db")).resolve(),
        export_root=Path(os.environ.get("BMA_BRIEFING_EXPORT_ROOT", root / "data" / "exports")).resolve(),
        public_url=public_url,
        session_secret=secret,
        bootstrap_users=_bootstrap_users(),
        ai_enabled=_bool("BMA_BRIEFING_AI_ENABLED"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
        development_email=os.environ.get("BMA_BRIEFING_DEVELOPMENT_EMAIL", "christo.bezuidenhout@bma.gov.za").strip().casefold(),
        refresh_timezone=os.environ.get("BMA_BRIEFING_REFRESH_TIMEZONE", "Africa/Johannesburg"),
        refresh_hour=int(os.environ.get("BMA_BRIEFING_REFRESH_HOUR", "6")),
        refresh_minute=int(os.environ.get("BMA_BRIEFING_REFRESH_MINUTE", "0")),
        build_version=os.environ.get("BMA_BRIEFING_BUILD_VERSION", "development").strip() or "development",
    )
