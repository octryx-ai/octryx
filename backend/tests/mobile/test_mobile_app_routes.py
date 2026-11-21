"""Octryx Mobile's Home Screen app under /m: the page loads without a login (the app signs itself in), never from
a cache; the manifest makes it a standalone app scoped to /m/; the service worker caches nothing."""

from __future__ import annotations

import pytest

from app.web.routers import mobile_app


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/m", "/m/", "/m/pair", "/m/confirm"])
async def test_the_app_page_loads_without_a_login_and_is_never_cached(client, path, tmp_path, monkeypatch):
    page = tmp_path / "m" / "index.html"
    page.parent.mkdir()
    page.write_text("<!doctype html><title>Octryx</title>", encoding="utf-8")
    monkeypatch.setattr(mobile_app, "_chat_app_dir", lambda: tmp_path)
    client.cookies.clear()
    response = await client.get(path)
    assert response.status_code == 200 and "<title>Octryx</title>" in response.text
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.asyncio
async def test_a_missing_build_is_a_plain_503(client, tmp_path, monkeypatch):
    monkeypatch.setattr(mobile_app, "_chat_app_dir", lambda: tmp_path)
    assert (await client.get("/m")).status_code == 503


@pytest.mark.asyncio
async def test_manifest_and_service_worker(client):
    manifest = await client.get("/m/manifest.webmanifest")
    assert manifest.status_code == 200 and manifest.headers["content-type"].startswith("application/manifest+json")
    body = manifest.json()
    assert body["start_url"] == "/m/" and body["scope"] == "/m/" and body["display"] == "standalone"
    assert {icon["sizes"] for icon in body["icons"]} == {"192x192", "512x512"}
    worker = await client.get("/m/sw.js")
    assert worker.status_code == 200 and worker.headers["content-type"].startswith("text/javascript")
    assert "caches." not in worker.text  # no cache of any API answer or page
    # phase 3: it shows notifications, opens only /m/ addresses from them and sets the badge
    assert 'addEventListener("push"' in worker.text and 'startsWith("/m/")' in worker.text
    assert "setAppBadge" in worker.text and "notificationclick" in worker.text
