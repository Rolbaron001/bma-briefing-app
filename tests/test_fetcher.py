from __future__ import annotations

import ipaddress

import httpx
import pytest

from app import fetcher


def test_private_and_credentialed_urls_are_rejected(monkeypatch):
    monkeypatch.setattr(fetcher, "_resolved_addresses", lambda _host: {ipaddress.ip_address("127.0.0.1")})
    with pytest.raises(fetcher.FetchError):
        fetcher.validate_public_https_url("https://example.org/data")
    with pytest.raises(fetcher.FetchError):
        fetcher.validate_public_https_url("https://user:pass@example.org/data")
    with pytest.raises(fetcher.FetchError):
        fetcher.validate_public_https_url("http://example.org/data")


def test_safe_get_bounds_redirects_and_body(monkeypatch):
    monkeypatch.setattr(fetcher, "_resolved_addresses", lambda _host: {ipaddress.ip_address("93.184.216.34")})
    redirect_client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"location":str(request.url)}, request=request)
    ))
    with pytest.raises(fetcher.FetchError, match="redirect"):
        fetcher.safe_get("https://example.org/data", client=redirect_client)
    body_client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"x" * 20, request=request)
    ))
    with pytest.raises(fetcher.FetchError, match="large"):
        fetcher.safe_get("https://example.org/data", max_bytes=10, client=body_client)


def test_rss_rejects_non_google_article_links(monkeypatch):
    xml = b"""<rss><channel><item><title>Story</title><link>javascript:alert(1)</link><source>Bad</source></item></channel></rss>"""
    monkeypatch.setattr(fetcher, "safe_get", lambda *args, **kwargs: xml)
    assert fetcher.fetch_google_news("test") == []

