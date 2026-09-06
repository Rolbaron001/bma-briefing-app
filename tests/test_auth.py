from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.auth import establish_identity, microsoft_issuer
from app.bootstrap import initialise


def test_public_and_protected_route_boundaries(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/login").status_code == 200
    assert client.get("/", follow_redirects=False).status_code == 303
    assert client.get("/api/me").status_code == 401
    assert client.post("/api/refresh").status_code == 401
    assert client.get("/assets/styles.css").status_code == 200


def test_development_login_rotates_session_and_uses_approved_account(client):
    first = client.get("/auth/development", follow_redirects=False)
    assert first.status_code == 303
    me = client.get("/api/me")
    assert me.json()["email"] == "admin@example.org"
    assert me.json()["role"] == "admin"
    assert me.json()["buildVersion"] == "development"
    assert me.json()["csrf"]


def test_csrf_and_role_are_enforced(admin_client):
    token = admin_client.headers.pop("X-CSRF-Token")
    assert admin_client.post("/api/refresh").status_code == 403
    admin_client.headers["X-CSRF-Token"] = token
    factory = admin_client.app.state.factory
    from app.models import AppUser
    with factory.begin() as db:
        row = db.query(AppUser).filter_by(email="admin@example.org").one()
        row.role = "viewer"
    assert admin_client.post("/api/refresh").status_code == 403


def test_google_identity_requires_verified_email(settings):
    engine, factory = initialise(settings)
    try:
        with pytest.raises(HTTPException):
            establish_identity(factory, {"iss":"https://accounts.google.com","sub":"1",
                                         "email":"admin@example.org","email_verified":False}, "google", None)
        user = establish_identity(factory, {"iss":"https://accounts.google.com","sub":"1",
                                            "email":"admin@example.org","email_verified":True}, "google", None)
        assert user.email == "admin@example.org"
    finally:
        engine.dispose()


def test_unapproved_and_untrusted_issuers_are_rejected(settings):
    engine, factory = initialise(settings)
    try:
        with pytest.raises(HTTPException):
            establish_identity(factory, {"iss":"https://evil.example","sub":"1",
                                         "email":"admin@example.org","email_verified":True}, "google", None)
        with pytest.raises(HTTPException):
            establish_identity(factory, {"iss":"https://accounts.google.com","sub":"2",
                                         "email":"other@example.org","email_verified":True}, "google", None)
    finally:
        engine.dispose()


def test_microsoft_issuer_requires_matching_tenant():
    issuer = "https://login.microsoftonline.com/01234567-89ab-cdef-0123-456789abcdef/v2.0"
    assert microsoft_issuer({"tid":"01234567-89ab-cdef-0123-456789abcdef"}, issuer)
    assert not microsoft_issuer({"tid":"different"}, issuer)
