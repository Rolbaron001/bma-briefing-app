from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from .models import AppUser, AuditEvent, UserIdentity, utc_now

ROLES = {"viewer", "analyst", "admin"}
MICROSOFT_ISSUER = re.compile(
    r"https://login\.microsoftonline\.com/(?P<tenant>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/v2\.0",
    re.I,
)


@dataclass(frozen=True)
class User:
    id: int
    email: str
    role: str
    display_name: str | None


def microsoft_issuer(claims: dict, issuer: object) -> bool:
    if not isinstance(issuer, str) or not (match := MICROSOFT_ISSUER.fullmatch(issuer)):
        return False
    tenant = claims.get("tid")
    return isinstance(tenant, str) and tenant.casefold() == match.group("tenant").casefold()


def microsoft_claims_options() -> dict:
    return {
        "iss": {"essential": True, "validate": microsoft_issuer},
        "tid": {
            "essential": True,
            "validate": lambda claims, value: isinstance(value, str) and microsoft_issuer(claims, claims.get("iss")),
        },
    }


def register_oauth() -> OAuth:
    import os

    oauth = OAuth()
    if os.environ.get("MICROSOFT_CLIENT_ID") and os.environ.get("MICROSOFT_CLIENT_SECRET"):
        oauth.register(
            "microsoft",
            client_id=os.environ["MICROSOFT_CLIENT_ID"],
            client_secret=os.environ["MICROSOFT_CLIENT_SECRET"],
            server_metadata_url="https://login.microsoftonline.com/organizations/v2.0/.well-known/openid-configuration",
            client_kwargs={"scope": "openid profile email"},
        )
    if os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"):
        oauth.register(
            "google",
            client_id=os.environ["GOOGLE_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid profile email"},
        )
    return oauth


def to_user(row: AppUser) -> User:
    return User(row.id, row.email, row.role, row.display_name)


def current_user(factory: sessionmaker):
    def dependency(request: Request) -> User:
        user_id = request.session.get("user_id")
        if not user_id:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
        with factory() as db:
            row = db.get(AppUser, int(user_id))
            if not row or not row.is_active:
                request.session.clear()
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is inactive")
            return to_user(row)

    return dependency


def require_role(factory: sessionmaker, *roles: str):
    permitted = set(roles)

    def dependency(user: User = Depends(current_user(factory))) -> User:
        if user.role not in permitted:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    return dependency


def csrf_guard(request: Request) -> None:
    expected = request.session.get("csrf")
    received = request.headers.get("X-CSRF-Token")
    if not expected or not received or not secrets.compare_digest(expected, received):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF validation failed")


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else None)


def add_audit(db, user: User | None, action: str, request: Request | None = None,
              resource_type: str | None = None, resource_id: str | None = None,
              detail: dict | None = None) -> None:
    db.add(AuditEvent(
        actor_user_id=user.id if user else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail_json=json.dumps(detail or {}, separators=(",", ":")),
        client_ip=client_ip(request) if request else None,
    ))


def establish_identity(factory: sessionmaker, claims: dict, provider: str, request: Request | None) -> User:
    if provider not in {"microsoft", "google", "development"}:
        raise HTTPException(403, "Unsupported identity provider")
    issuer = str(claims.get("iss") or "")
    subject = str(claims.get("sub") or "")
    email = str(claims.get("email") or claims.get("preferred_username") or "").strip().casefold()
    if not subject or not email or not issuer:
        raise HTTPException(403, "Provider did not return an approved identity")
    if provider == "microsoft" and not microsoft_issuer(claims, issuer):
        raise HTTPException(403, "Microsoft identity issuer is not trusted")
    if provider == "google" and issuer not in {"https://accounts.google.com", "accounts.google.com"}:
        raise HTTPException(403, "Google identity issuer is not trusted")
    if provider == "development" and issuer != "development":
        raise HTTPException(403, "Development identity issuer is not trusted")
    if provider == "google" and claims.get("email_verified") is not True:
        raise HTTPException(403, "Google email address is not verified")
    with factory.begin() as db:
        identity = db.scalar(select(UserIdentity).where(
            UserIdentity.issuer == issuer, UserIdentity.subject == subject
        ))
        if identity:
            row = db.get(AppUser, identity.user_id)
            if not row or not row.is_active:
                raise HTTPException(403, "Account is inactive")
            identity.last_login_at = utc_now()
        else:
            row = db.scalar(select(AppUser).where(AppUser.email == email, AppUser.is_active.is_(True)))
            if not row:
                raise HTTPException(403, "This email address is not approved")
            db.add(UserIdentity(
                user_id=row.id,
                issuer=issuer,
                subject=subject,
                email_at_link=email,
                last_login_at=utc_now(),
            ))
        user = to_user(row)
        add_audit(db, user, "login", request, "user", str(row.id), {"provider": provider})
        return user
