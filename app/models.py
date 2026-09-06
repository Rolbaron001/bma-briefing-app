from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint, text)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = (CheckConstraint("role IN ('viewer','analyst','admin')", name="ck_app_user_role"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")
    display_name: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class UserIdentity(Base):
    __tablename__ = "user_identity"
    __table_args__ = (UniqueConstraint("issuer", "subject"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    issuer: Mapped[str] = mapped_column(String(500), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    email_at_link: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)


class AuditEvent(Base):
    __tablename__ = "audit_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(100))
    resource_id: Mapped[str | None] = mapped_column(String(100))
    detail_json: Mapped[str | None] = mapped_column(Text)
    client_ip: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class BriefRun(Base):
    __tablename__ = "brief_run"
    __table_args__ = (
        CheckConstraint("trigger IN ('manual','scheduled')", name="ck_brief_run_trigger"),
        CheckConstraint("status IN ('queued','running','succeeded','failed','interrupted')", name="ck_brief_run_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    initiated_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    queued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(String(500))


class Article(Base):
    __tablename__ = "article"
    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    headline: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_name: Mapped[str] = mapped_column(String(300), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    published_label: Mapped[str | None] = mapped_column(String(100))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class BriefRunArticle(Base):
    __tablename__ = "brief_run_article"
    __table_args__ = (UniqueConstraint("run_id", "article_id", "area", "subcategory"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("brief_run.id", ondelete="CASCADE"), nullable=False)
    article_id: Mapped[int] = mapped_column(ForeignKey("article.id"), nullable=False)
    area: Mapped[str] = mapped_column(String(20), nullable=False)
    subcategory: Mapped[str | None] = mapped_column(String(300))
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="sa")
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Interest(Base):
    __tablename__ = "interest"
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    query: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class WatchItem(Base):
    __tablename__ = "watch_item"
    __table_args__ = (
        CheckConstraint("status IN ('open','archived')", name="ck_watch_item_status"),
        Index("uq_watch_item_open_article", "article_id", unique=True, sqlite_where=text("status = 'open'")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("article.id"), nullable=False)
    area: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    pinned_by: Mapped[int] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    pinned_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    archived_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)


class WatchNote(Base):
    __tablename__ = "watch_note"
    id: Mapped[int] = mapped_column(primary_key=True)
    watch_item_id: Mapped[int] = mapped_column(ForeignKey("watch_item.id", ondelete="CASCADE"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class Assessment(Base):
    __tablename__ = "assessment"
    __table_args__ = (CheckConstraint(
        "product_type IN ('Threat Assessment','Risk Assessment','Modus Operandi Profile','Watch Note')",
        name="ck_assessment_product",
    ),)
    id: Mapped[int] = mapped_column(primary_key=True)
    product_type: Mapped[str] = mapped_column(String(100), nullable=False)
    query: Mapped[str] = mapped_column(String(2000), nullable=False)
    result: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[int] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class AssessmentArticle(Base):
    __tablename__ = "assessment_article"
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessment.id", ondelete="CASCADE"), primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("article.id"), primary_key=True)


class ExportArtifact(Base):
    __tablename__ = "export_artifact"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(String(300), nullable=False)
    storage_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    media_type: Mapped[str] = mapped_column(String(200), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    assessment_id: Mapped[int | None] = mapped_column(ForeignKey("assessment.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class LegacyImport(Base):
    __tablename__ = "legacy_import"
    id: Mapped[int] = mapped_column(primary_key=True)
    content_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    imported_by: Mapped[int] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    detail_json: Mapped[str | None] = mapped_column(Text)


class UserPreference(Base):
    __tablename__ = "user_preference"
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime)


class RefreshLock(Base):
    __tablename__ = "refresh_lock"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    owner_token: Mapped[str | None] = mapped_column(String(100))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("brief_run.id"))
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime)
