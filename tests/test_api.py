from __future__ import annotations

import hashlib

from app.models import Article, BriefRun, BriefRunArticle, UserPreference, utc_now


def add_current_article(client) -> int:
    factory = client.app.state.factory
    with factory.begin() as db:
        run = BriefRun(trigger="manual", status="succeeded", completed_at=utc_now())
        db.add(run); db.flush()
        article = Article(fingerprint="a" * 64, headline="Border report", source_name="Publisher",
                          source_url="https://news.google.com/articles/example", published_label="01 Jan 2026",
                          summary="A relevant open-source report.")
        db.add(article); db.flush()
        db.add(BriefRunArticle(run_id=run.id, article_id=article.id, area="a", subcategory="Human Smuggling", scope="sa", rank=0))
        return article.id


def test_brief_watch_note_and_archive_flow(admin_client):
    article_id = add_current_article(admin_client)
    brief = admin_client.get("/api/brief").json()
    assert brief["clusters"]["a"][0]["id"] == article_id
    pinned = admin_client.post("/api/watchlist", json={"articleId":article_id,"area":"a"})
    assert pinned.status_code == 200
    watch_id = pinned.json()["id"]
    assert admin_client.post(f"/api/watchlist/{watch_id}/notes", json={"text":"Track this."}).status_code == 200
    assert admin_client.post(f"/api/watchlist/{watch_id}/archive").status_code == 200
    watch = admin_client.get("/api/watchlist").json()
    assert not watch["open"]
    assert watch["archived"][0]["notes"][0]["text"] == "Track this."


def test_unknown_and_browser_grounding_fields_are_rejected(admin_client):
    response = admin_client.post("/api/assessments", json={
        "product":"Threat Assessment", "query":"Question", "articleIds":[], "grounding":"forged"
    })
    assert response.status_code == 422


def test_brief_get_is_read_only_and_view_marker_requires_csrf(admin_client):
    factory = admin_client.app.state.factory
    user_id = admin_client.get("/api/me").json()["id"]
    assert admin_client.get("/api/brief").status_code == 200
    with factory() as db:
        assert db.get(UserPreference, user_id) is None
    token = admin_client.headers.pop("X-CSRF-Token")
    assert admin_client.post("/api/brief/viewed").status_code == 403
    admin_client.headers["X-CSRF-Token"] = token
    assert admin_client.post("/api/brief/viewed").status_code == 200
    with factory() as db:
        assert db.get(UserPreference, user_id).last_viewed_at is not None


def test_interest_and_user_administration(admin_client):
    created = admin_client.post("/api/interests", json={"label":"Gold", "query":"gold smuggling"})
    assert created.status_code == 200
    assert admin_client.delete(f"/api/interests/{created.json()['id']}").status_code == 200
    user = admin_client.post("/api/users", json={"email":"analyst@example.org","role":"analyst"})
    assert user.status_code == 200
    assert any(row["email"] == "analyst@example.org" for row in admin_client.get("/api/users").json()["users"])


def test_legacy_import_is_transactional_and_idempotent(admin_client):
    payload = {"format":"nbtc-brief-legacy","version":1,"state":{
        "interests":[{"label":"Port","query":"port security"}],
        "watchlist":[{"headline":"Legacy report","url":"https://news.google.com/articles/legacy",
                      "sourceName":"Source","area":"a","notes":[{"text":"Old note"}]}],
        "archive":[],
        "assessments":[{"product":"Watch Note","query":"Legacy question","result":"Legacy result"}],
    }}
    first = admin_client.post("/api/import/legacy", json=payload)
    second = admin_client.post("/api/import/legacy", json=payload)
    assert first.status_code == 200 and first.json()["duplicate"] is False
    assert second.status_code == 200 and second.json()["duplicate"] is True
    assert admin_client.get("/api/watchlist").json()["open"][0]["notes"][0]["text"] == "Old note"
