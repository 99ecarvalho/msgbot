# Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>
#
# This file is part of MsgBot. It is free software, licensed under the GNU
# Lesser General Public License v3.0 or later. See COPYING.LESSER and
# COPYING for details.
#
# SPDX-License-Identifier: LGPL-3.0-or-later

"""Web UI login, CSRF protection, and webhook secrets."""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from bot import db
from bot.main import app
from bot.web import auth

HOST = "testserver"


@asynccontextmanager
async def _no_startup(_app):
    # The real lifespan registers webhooks with Evolution API and Telegram.
    yield
    await db.close_db()


@pytest.fixture(scope="module")
def _session_client():
    app.router.lifespan_context = _no_startup
    with TestClient(app, follow_redirects=False) as c:  # one event loop for all tests
        yield c


@pytest.fixture
def client(_session_client):
    _session_client.cookies.clear()
    return _session_client


@pytest.fixture
def logged_in(client):
    r = client.post("/login", data={"username": "admin", "password": "test-password", "next": "/logs"})
    assert r.status_code == 303
    return client


def test_pages_redirect_to_login(client):
    r = client.get("/logs?level=error", headers={"Accept": "text/html"})
    assert r.status_code == 303
    assert r.headers["location"] == "/login?next=/logs%3Flevel%3Derror"


def test_htmx_and_api_requests_get_401(client):
    r = client.post("/config", headers={"HX-Request": "true"})
    assert r.status_code == 401
    assert r.headers["HX-Redirect"] == "/login"
    assert client.get("/audios/in/x.ogg").status_code == 401


def test_public_paths(client):
    assert client.get("/health").status_code == 200
    assert client.get("/login").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_wrong_password(client):
    r = client.post("/login", data={"username": "admin", "password": "nope"})
    assert r.status_code == 401
    assert auth.SESSION_COOKIE not in r.cookies


def test_login_sets_strict_httponly_cookie_and_redirects(client):
    r = client.post("/login", data={"username": "admin", "password": "test-password", "next": "/logs"})
    assert r.status_code == 303
    assert r.headers["location"] == "/logs"
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie


@pytest.mark.parametrize("target", ["https://evil.example", "//evil.example", "javascript:alert(1)"])
def test_login_never_redirects_off_site(client, target):
    r = client.post("/login", data={"username": "admin", "password": "test-password", "next": target})
    assert r.headers["location"] == "/"


def test_logged_in_can_browse(logged_in):
    assert logged_in.get("/logs").status_code == 200


def test_cross_site_post_is_blocked(logged_in):
    r = logged_in.post("/messages/whitelist-remove", data={"entry_id": "0"},
                       headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = logged_in.post("/messages/whitelist-remove", data={"entry_id": "0"},
                       headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_same_origin_post_is_allowed(logged_in):
    r = logged_in.post("/messages/whitelist-remove", data={"entry_id": "0"},
                       headers={"Sec-Fetch-Site": "same-origin", "Origin": f"http://{HOST}"})
    assert r.status_code == 200


def test_logout_ends_session(logged_in):
    assert logged_in.post("/logout").status_code == 303
    logged_in.cookies.clear()
    assert logged_in.get("/logs").status_code == 401


def test_session_tampering_and_expiry():
    good = auth.make_session()
    assert auth.valid_session(good)
    expiry, sig = good.split(".")
    assert not auth.valid_session(f"{int(expiry) + 1}.{sig}")
    assert not auth.valid_session(good, now=time.time() + auth.SESSION_MAX_AGE + 1)
    assert not auth.valid_session("garbage")


def test_websocket_requires_login(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/logs"):
            pass


def test_websocket_rejects_other_origins(logged_in):
    with pytest.raises(WebSocketDisconnect):
        with logged_in.websocket_connect("/ws/logs", headers={"Origin": "https://evil.example"}):
            pass


def test_websocket_works_when_logged_in(logged_in):
    with logged_in.websocket_connect("/ws/logs", headers={"Origin": f"http://{HOST}"}) as ws:
        assert ws  # handshake accepted


def test_whatsapp_webhook_needs_the_secret(client):
    assert client.post("/webhook/whatsapp", json={}).status_code == 403
    r = client.post("/webhook/whatsapp", json={},
                    headers={auth.WHATSAPP_WEBHOOK_HEADER: "wrong"})
    assert r.status_code == 403
    r = client.post("/webhook/whatsapp", json={},
                    headers={auth.WHATSAPP_WEBHOOK_HEADER: auth.whatsapp_webhook_secret()})
    assert r.status_code == 200


def test_telegram_webhook_rejected_without_token_or_secret(client):
    # TELEGRAM_BOT_TOKEN is empty in the tests: Telegram is disabled
    r = client.post("/webhook/telegram", json={},
                    headers={auth.TELEGRAM_SECRET_HEADER: auth.telegram_webhook_secret()})
    assert r.status_code == 403
