from __future__ import annotations

import hashlib
import ipaddress
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool

from .auth import (ROLES, User, add_audit, csrf_guard, current_user, establish_identity,
                   microsoft_claims_options, register_oauth, require_role)
from .bootstrap import initialise, migration_is_current
from .models import (AppUser, Article, Assessment, AuditEvent, BriefRun, ExportArtifact, Interest,
                     LegacyImport, UserPreference, WatchItem, WatchNote, utc_now)
from .services import (PRODUCT_TYPES, assessment_payload, create_archive_export,
                       create_assessment_export, create_refresh_run, export_path,
                       generate_assessment, latest_brief, run_refresh, watchlist_payload)
from .settings import Settings, load_settings


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InterestInput(StrictInput):
    label: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=500)

    @field_validator("label", "query")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class WatchInput(StrictInput):
    articleId: int
    area: str = Field(default="", max_length=20)


class NoteInput(StrictInput):
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class AssessmentInput(StrictInput):
    product: str
    query: str = Field(min_length=1, max_length=2000)
    articleIds: list[int] = Field(default_factory=list, max_length=50)


class ExportInput(StrictInput):
    kind: str
    assessmentId: int | None = None
    format: str = "markdown"


class UserInput(StrictInput):
    id: int | None = None
    email: str = Field(min_length=3, max_length=320)
    role: str = "viewer"
    display_name: str | None = Field(default=None, max_length=200)
    is_active: bool = True


def _artifact_dict(row: ExportArtifact) -> dict:
    return {
        "id": row.id, "kind": row.kind, "name": row.display_name, "size": row.size_bytes,
        "assessmentId": row.assessment_id, "createdBy": row.created_by,
        "createdAt": row.created_at.isoformat() + "Z",
    }


async def bounded_body(request: Request, settings: Settings) -> bytes:
    try:
        declared = int(request.headers.get("content-length", "0") or 0)
    except ValueError as exc:
        raise HTTPException(400, "Invalid Content-Length") from exc
    if declared > settings.max_json_bytes:
        raise HTTPException(413, "Request body is too large")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > settings.max_json_bytes:
            raise HTTPException(413, "Request body is too large")
    return bytes(raw)


async def bounded_json(request: Request, settings: Settings) -> dict:
    raw = await bounded_body(request, settings)
    try:
        value = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Invalid JSON") from exc
    if not isinstance(value, dict):
        raise HTTPException(400, "A JSON object is required")
    return value


def parse_input(model_type, value: dict):
    try:
        return model_type.model_validate(value)
    except ValidationError as exc:
        raise HTTPException(422, "Request validation failed") from exc


def localhost_request(request: Request) -> bool:
    host = request.client.host if request.client else ""
    if host == "testclient":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    engine = None
    factory = None
    oauth = register_oauth()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal engine, factory
        engine, factory = initialise(settings)
        app.state.engine = engine
        app.state.factory = factory
        app.state.ready = True
        yield
        app.state.ready = False
        engine.dispose()

    app = FastAPI(title="BMA National Border Targeting Centre Brief", docs_url=None,
                  redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret,
                       https_only=settings.secure_cookies, same_site="lax", max_age=8 * 60 * 60)

    def db_factory():
        if factory is None:
            raise HTTPException(503, "Application is starting")
        return factory

    def user_dep(request: Request) -> User:
        return current_user(db_factory())(request)

    def analyst_dep(request: Request) -> User:
        return require_role(db_factory(), "analyst", "admin")(user_dep(request))

    def admin_dep(request: Request) -> User:
        return require_role(db_factory(), "admin")(user_dep(request))

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        if settings.secure_cookies:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path == "/" or request.url.path.startswith(("/api/", "/auth/", "/login", "/logout", "/legacy-export")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(IntegrityError)
    async def conflict_handler(_request: Request, _exc: IntegrityError):
        return JSONResponse({"detail": "The requested change conflicts with existing data"}, status_code=409)

    @app.get("/healthz")
    def healthz():
        if not getattr(app.state, "ready", False) or not migration_is_current(settings):
            return JSONResponse({"ok": False}, status_code=503)
        return {"ok": True}

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(settings.app_root / "bma.ico", media_type="image/x-icon")

    @app.get("/")
    def index(request: Request):
        try:
            user_dep(request)
        except HTTPException as exc:
            if exc.status_code == 401:
                return RedirectResponse("/login", status_code=303)
            raise
        return FileResponse(settings.app_root / "app" / "templates" / "index.html", media_type="text/html")

    @app.get("/legacy-export")
    def legacy_export(_: User = Depends(admin_dep)):
        return FileResponse(settings.app_root / "app" / "templates" / "legacy.html", media_type="text/html")

    @app.get("/login")
    def login(request: Request):
        providers = [name for name in ("microsoft", "google") if oauth.create_client(name)]
        links = "".join(f'<p><a href="/auth/{name}">Sign in with {name.title()}</a></p>' for name in providers)
        if settings.development_auth_enabled:
            links += '<p><a href="/auth/development">Development sign in</a></p>'
        return HTMLResponse(
            "<!doctype html><html><head><meta charset='utf-8'><title>NBTC Brief sign in</title>"
            "<link rel='stylesheet' href='/assets/styles.css'></head><body><main class='login'>"
            "<h1>National Border Targeting Centre Brief</h1><p>Sign in with an approved account.</p>"
            f"{links or '<p>No identity provider is configured.</p>'}</main></body></html>"
        )

    @app.get("/auth/{provider}")
    async def auth_start(provider: str, request: Request):
        if provider == "development":
            if not settings.development_auth_enabled or not localhost_request(request):
                raise HTTPException(404)
            user = establish_identity(db_factory(), {
                "iss": "development", "sub": settings.development_email,
                "email": settings.development_email, "email_verified": True,
            }, "development", request)
            request.session.clear()
            request.session.update({"user_id": user.id, "csrf": secrets.token_urlsafe(32)})
            return RedirectResponse("/", status_code=303)
        client = oauth.create_client(provider) if provider in {"microsoft", "google"} else None
        if not client:
            raise HTTPException(404, "Identity provider is not configured")
        return await client.authorize_redirect(request, f"{settings.public_url}/auth/{provider}/callback")

    @app.get("/auth/{provider}/callback")
    async def auth_callback(provider: str, request: Request):
        client = oauth.create_client(provider) if provider in {"microsoft", "google"} else None
        if not client:
            raise HTTPException(404)
        options = microsoft_claims_options() if provider == "microsoft" else None
        token = await client.authorize_access_token(request, claims_options=options)
        claims = token.get("userinfo") or await client.userinfo(token=token)
        user = establish_identity(db_factory(), dict(claims), provider, request)
        request.session.clear()
        request.session.update({"user_id": user.id, "csrf": secrets.token_urlsafe(32)})
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    def logout(request: Request, _: User = Depends(user_dep), __: None = Depends(csrf_guard)):
        request.session.clear()
        return {"ok": True}

    @app.get("/api/me")
    def me(request: Request, user: User = Depends(user_dep)):
        return {"id": user.id, "email": user.email, "displayName": user.display_name,
                "role": user.role, "csrf": request.session["csrf"],
                "aiEnabled": bool(settings.ai_enabled and settings.anthropic_api_key)}

    @app.get("/api/brief")
    def brief(user: User = Depends(user_dep)):
        with db_factory()() as db:
            preference = db.get(UserPreference, user.id)
            prior = preference.last_viewed_at if preference else None
        payload = latest_brief(db_factory())
        payload["previouslyViewedAt"] = prior.isoformat() + "Z" if prior else None
        return payload

    @app.post("/api/brief/viewed")
    def mark_brief_viewed(user: User = Depends(user_dep), _: None = Depends(csrf_guard)):
        with db_factory().begin() as db:
            preference = db.get(UserPreference, user.id)
            if not preference:
                preference = UserPreference(user_id=user.id)
                db.add(preference)
            preference.last_viewed_at = utc_now()
        return {"ok": True}

    @app.post("/api/refresh", status_code=status.HTTP_202_ACCEPTED)
    def refresh(request: Request, background: BackgroundTasks, user: User = Depends(analyst_dep),
                _: None = Depends(csrf_guard)):
        run_id = create_refresh_run(db_factory(), "manual", user.id)
        with db_factory().begin() as db:
            add_audit(db, user, "brief.refresh", request, "brief_run", str(run_id))
        background.add_task(run_refresh, db_factory(), run_id)
        return {"id": run_id, "status": "queued"}

    @app.get("/api/refresh/{run_id}")
    def refresh_status(run_id: int, _: User = Depends(user_dep)):
        with db_factory()() as db:
            row = db.get(BriefRun, run_id)
            if not row:
                raise HTTPException(404, "Refresh not found")
            return {"id": row.id, "status": row.status, "error": row.error_message,
                    "startedAt": row.started_at.isoformat() + "Z" if row.started_at else None,
                    "completedAt": row.completed_at.isoformat() + "Z" if row.completed_at else None}

    @app.get("/api/interests")
    def list_interests(_: User = Depends(user_dep)):
        with db_factory()() as db:
            return {"interests": [{"id": row.id, "label": row.label, "query": row.query}
                    for row in db.scalars(select(Interest).where(Interest.is_active.is_(True)).order_by(Interest.id))]}

    @app.post("/api/interests")
    async def save_interest(request: Request, user: User = Depends(analyst_dep), _: None = Depends(csrf_guard)):
        data = parse_input(InterestInput, await bounded_json(request, settings))
        with db_factory().begin() as db:
            row = Interest(label=data.label, query=data.query, created_by=user.id)
            db.add(row); db.flush()
            add_audit(db, user, "interest.create", request, "interest", str(row.id))
            return {"id": row.id}

    @app.delete("/api/interests/{interest_id}")
    def delete_interest(interest_id: int, request: Request, user: User = Depends(analyst_dep),
                        _: None = Depends(csrf_guard)):
        with db_factory().begin() as db:
            row = db.get(Interest, interest_id)
            if not row or not row.is_active:
                raise HTTPException(404, "Interest not found")
            row.is_active = False
            add_audit(db, user, "interest.deactivate", request, "interest", str(row.id))
        return {"ok": True}

    @app.get("/api/watchlist")
    def list_watchlist(_: User = Depends(user_dep)):
        return watchlist_payload(db_factory())

    @app.post("/api/watchlist")
    async def pin_watch(request: Request, user: User = Depends(analyst_dep), _: None = Depends(csrf_guard)):
        data = parse_input(WatchInput, await bounded_json(request, settings))
        with db_factory().begin() as db:
            article = db.get(Article, data.articleId)
            if not article:
                raise HTTPException(404, "Article not found")
            existing = db.scalar(select(WatchItem).where(WatchItem.article_id == article.id,
                                                         WatchItem.status == "open"))
            if existing:
                return {"id": existing.id}
            row = WatchItem(article_id=article.id, area=data.area, pinned_by=user.id)
            db.add(row); db.flush()
            add_audit(db, user, "watch.pin", request, "watch_item", str(row.id), {"article_id": article.id})
            return {"id": row.id}

    @app.post("/api/watchlist/{watch_id}/notes")
    async def add_note(watch_id: int, request: Request, user: User = Depends(analyst_dep),
                       _: None = Depends(csrf_guard)):
        data = parse_input(NoteInput, await bounded_json(request, settings))
        with db_factory().begin() as db:
            watch = db.get(WatchItem, watch_id)
            if not watch:
                raise HTTPException(404, "Watch item not found")
            if watch.status != "open":
                raise HTTPException(409, "Archived watch items cannot receive new notes")
            row = WatchNote(watch_item_id=watch.id, text=data.text, created_by=user.id)
            db.add(row); db.flush()
            add_audit(db, user, "watch.note", request, "watch_item", str(watch.id), {"note_id": row.id})
            return {"id": row.id}

    @app.post("/api/watchlist/{watch_id}/archive")
    def archive_watch(watch_id: int, request: Request, user: User = Depends(analyst_dep),
                      _: None = Depends(csrf_guard)):
        with db_factory().begin() as db:
            row = db.get(WatchItem, watch_id)
            if not row:
                raise HTTPException(404, "Watch item not found")
            row.status, row.archived_by, row.archived_at = "archived", user.id, utc_now()
            add_audit(db, user, "watch.archive", request, "watch_item", str(row.id))
        return {"ok": True}

    @app.get("/api/assessments")
    def list_assessments(_: User = Depends(user_dep)):
        return {"assessments": assessment_payload(db_factory())}

    @app.post("/api/assessments")
    async def create_assessment(request: Request, user: User = Depends(analyst_dep),
                                _: None = Depends(csrf_guard)):
        data = parse_input(AssessmentInput, await bounded_json(request, settings))
        if data.product not in PRODUCT_TYPES:
            raise HTTPException(400, "Unsupported assessment product")
        try:
            row = await run_in_threadpool(
                generate_assessment, settings, db_factory(), data.product,
                data.query.strip(), data.articleIds, user.id,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        with db_factory().begin() as db:
            add_audit(db, user, "assessment.create", request, "assessment", str(row.id),
                      {"article_count": len(data.articleIds), "product": data.product})
        return {"id": row.id, "result": row.result}

    @app.get("/api/exports")
    def list_exports(_: User = Depends(user_dep)):
        with db_factory()() as db:
            return {"exports": [_artifact_dict(row) for row in db.scalars(
                select(ExportArtifact).order_by(ExportArtifact.created_at.desc()))]}

    @app.post("/api/exports")
    async def create_export(request: Request, user: User = Depends(analyst_dep), _: None = Depends(csrf_guard)):
        data = parse_input(ExportInput, await bounded_json(request, settings))
        try:
            if data.kind == "assessment" and data.assessmentId:
                artifact = create_assessment_export(settings, db_factory(), data.assessmentId, user.id)
            elif data.kind == "archive" and data.format in {"markdown", "json"}:
                artifact = create_archive_export(settings, db_factory(), user.id, data.format)
            else:
                raise HTTPException(400, "Unsupported export request")
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        with db_factory().begin() as db:
            add_audit(db, user, "export.create", request, "export", str(artifact.id), {"kind": artifact.kind})
        return _artifact_dict(artifact)

    @app.get("/api/exports/{export_id}/download")
    def download_export(export_id: int, _: User = Depends(user_dep)):
        with db_factory()() as db:
            artifact = db.get(ExportArtifact, export_id)
            if not artifact:
                raise HTTPException(404, "Export not found")
            try:
                path = export_path(settings, artifact)
            except (ValueError, FileNotFoundError) as exc:
                raise HTTPException(404, "Export file is unavailable") from exc
            return FileResponse(path, media_type=artifact.media_type, filename=artifact.display_name)

    @app.delete("/api/exports/{export_id}")
    def delete_export(export_id: int, request: Request, user: User = Depends(admin_dep),
                      _: None = Depends(csrf_guard)):
        with db_factory().begin() as db:
            artifact = db.get(ExportArtifact, export_id)
            if not artifact:
                raise HTTPException(404, "Export not found")
            try:
                path = export_path(settings, artifact)
            except FileNotFoundError:
                path = None
            add_audit(db, user, "export.delete", request, "export", str(artifact.id))
            db.delete(artifact)
        if path:
            path.unlink(missing_ok=True)
        return {"ok": True}

    @app.get("/api/users")
    def list_users(_: User = Depends(admin_dep)):
        with db_factory()() as db:
            return {"users": [{"id": row.id, "email": row.email, "role": row.role,
                    "display_name": row.display_name, "is_active": row.is_active}
                    for row in db.scalars(select(AppUser).order_by(AppUser.email))]}

    @app.post("/api/users")
    async def save_user(request: Request, admin: User = Depends(admin_dep), _: None = Depends(csrf_guard)):
        data = parse_input(UserInput, await bounded_json(request, settings))
        email = data.email.strip().casefold()
        if "@" not in email or data.role not in ROLES:
            raise HTTPException(400, "A valid email and role are required")
        with db_factory().begin() as db:
            if data.id:
                row = db.get(AppUser, data.id)
                if not row:
                    raise HTTPException(404, "User not found")
                if row.id == admin.id and not data.is_active:
                    raise HTTPException(400, "You cannot deactivate your own account")
                if row.id == admin.id and data.role != "admin":
                    raise HTTPException(400, "You cannot remove your own administrator role")
                row.email, row.role = email, data.role
                row.display_name, row.is_active = data.display_name, data.is_active
            else:
                row = AppUser(email=email, role=data.role, display_name=data.display_name,
                              is_active=data.is_active)
                db.add(row)
            db.flush()
            add_audit(db, admin, "user.save", request, "user", str(row.id),
                      {"email": email, "role": data.role, "active": data.is_active})
            return {"id": row.id}

    @app.get("/api/audit")
    def list_audit(_: User = Depends(admin_dep)):
        with db_factory()() as db:
            rows = list(db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(200)))
            return {"events": [{"id": row.id, "actorUserId": row.actor_user_id, "action": row.action,
                    "resourceType": row.resource_type, "resourceId": row.resource_id,
                    "createdAt": row.created_at.isoformat() + "Z"} for row in rows]}

    @app.post("/api/import/legacy")
    async def import_legacy(request: Request, admin: User = Depends(admin_dep), _: None = Depends(csrf_guard)):
        raw = await bounded_body(request, settings)
        digest = hashlib.sha256(raw).hexdigest()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, "Invalid legacy JSON") from exc
        if not isinstance(data, dict) or data.get("format") != "nbtc-brief-legacy" or data.get("version") != 1:
            raise HTTPException(400, "Unsupported legacy export")
        state = data.get("state")
        if not isinstance(state, dict):
            raise HTTPException(400, "Legacy state is missing")
        with db_factory().begin() as db:
            existing = db.scalar(select(LegacyImport).where(LegacyImport.content_sha256 == digest))
            if existing:
                return {"ok": True, "duplicate": True, "importId": existing.id}
            counts = {"interests": 0, "watchlist": 0, "archive": 0, "notes": 0, "assessments": 0}
            interests = state.get("interests", [])
            watchlists = {key: state.get(key, []) for key in ("watchlist", "archive")}
            assessments = state.get("assessments", [])
            if not isinstance(interests, list) or len(interests) > 100:
                raise HTTPException(400, "Invalid legacy interests")
            if any(not isinstance(values, list) or len(values) > 1000 for values in watchlists.values()):
                raise HTTPException(400, "Invalid legacy watch records")
            if not isinstance(assessments, list) or len(assessments) > 500:
                raise HTTPException(400, "Invalid legacy assessments")
            for value in interests:
                if not isinstance(value, dict):
                    raise HTTPException(400, "Invalid legacy interest")
                label, query = str(value.get("label") or "").strip(), str(value.get("query") or "").strip()
                if not label or not query or len(label) > 200 or len(query) > 500:
                    raise HTTPException(400, "Invalid legacy interest")
                db.add(Interest(label=label, query=query, created_by=admin.id)); counts["interests"] += 1
            for status_name, key in (("open", "watchlist"), ("archived", "archive")):
                for value in watchlists[key]:
                    if not isinstance(value, dict):
                        raise HTTPException(400, "Invalid legacy watch item")
                    headline = str(value.get("headline") or "").strip()[:1000]
                    url = str(value.get("url") or "").strip()
                    if not headline or not url.startswith("https://"):
                        raise HTTPException(400, "Invalid legacy article")
                    fingerprint = hashlib.sha256(f"{url}\n{headline}".casefold().encode()).hexdigest()
                    article = db.scalar(select(Article).where(Article.fingerprint == fingerprint))
                    if not article:
                        article = Article(fingerprint=fingerprint, headline=headline,
                                          source_name=str(value.get("sourceName") or "Legacy import")[:300],
                                          source_url=url, published_label=str(value.get("date") or "recent")[:100],
                                          summary=str(value.get("note") or "")[:4000])
                        db.add(article); db.flush()
                    watch = WatchItem(article_id=article.id, area=str(value.get("area") or "")[:20],
                                      status=status_name, pinned_by=admin.id,
                                      archived_by=admin.id if status_name == "archived" else None,
                                      archived_at=utc_now() if status_name == "archived" else None)
                    db.add(watch); db.flush(); counts[key] += 1
                    notes = value.get("notes", [])
                    if not isinstance(notes, list) or len(notes) > 500:
                        raise HTTPException(400, "Invalid legacy notes")
                    for note in notes:
                        text = str(note.get("text") if isinstance(note, dict) else "").strip()
                        if not text or len(text) > 4000:
                            raise HTTPException(400, "Invalid legacy note")
                        db.add(WatchNote(watch_item_id=watch.id, text=text, created_by=admin.id)); counts["notes"] += 1
            for value in assessments:
                if not isinstance(value, dict):
                    raise HTTPException(400, "Invalid legacy assessment")
                product = str(value.get("product") or "")
                query, result = str(value.get("query") or "").strip(), str(value.get("result") or "").strip()
                if product not in PRODUCT_TYPES or not query or not result:
                    raise HTTPException(400, "Invalid legacy assessment")
                db.add(Assessment(product_type=product, query=query[:2000], result=result[:100000],
                                  model="legacy-import", created_by=admin.id)); counts["assessments"] += 1
            record = LegacyImport(content_sha256=digest, imported_by=admin.id,
                                  detail_json=json.dumps(counts, separators=(",", ":")))
            db.add(record); db.flush()
            add_audit(db, admin, "legacy.import", request, "legacy_import", str(record.id), counts)
            return {"ok": True, "duplicate": False, "importId": record.id, "counts": counts}

    app.mount("/assets", StaticFiles(directory=settings.app_root / "app" / "static"), name="assets")
    return app


app = create_app()
