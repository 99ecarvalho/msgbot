# Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>
#
# This file is part of MsgBot. It is free software, licensed under the GNU
# Lesser General Public License v3.0 or later. See COPYING.LESSER and
# COPYING for details.
#
# SPDX-License-Identifier: LGPL-3.0-or-later

"""Web UI authentication and webhook secrets.

- The web UI (pages, htmx endpoints, audio files, WebSockets) requires a
  login. A successful login sets a signed, HttpOnly, SameSite=Strict session
  cookie.
- State-changing requests and WebSockets must come from the UI's own origin,
  so another site can't use the operator's session (CSRF).
- Webhooks are exempt from the login and check their own secret instead:
  Telegram sends the secret_token we register, Evolution API sends a header
  we configure on the instance.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
from urllib.parse import quote, urlsplit

import structlog
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from bot.config import settings

log = structlog.get_logger("web.auth")

SESSION_COOKIE = "msgbot_session"
SESSION_MAX_AGE = 7 * 24 * 3600  # seconds
WHATSAPP_WEBHOOK_HEADER = "X-MsgBot-Webhook-Token"
TELEGRAM_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"

# Paths reachable without logging in. Webhooks verify their own secret.
_PUBLIC_PREFIXES = ("/static/",)
_PUBLIC_PATHS = {"/login", "/health", "/webhook/telegram", "/webhook/whatsapp"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Without WEB_PASSWORD, use a random password for this run and log it once, so
# the UI is never left open.
_generated_password = ""


def web_password() -> str:
    global _generated_password
    if settings.web_password:
        return settings.web_password
    if not _generated_password:
        _generated_password = secrets.token_urlsafe(16)
        log.warning(
            "web_password_generated",
            username=settings.web_username,
            password=_generated_password,
            hint="Set WEB_PASSWORD in .env to keep a fixed password",
        )
    return _generated_password


def _derive(key: str, purpose: str) -> str:
    return hmac.new(key.encode(), purpose.encode(), hashlib.sha256).hexdigest()


def whatsapp_webhook_secret() -> str:
    """Secret that Evolution API sends in WHATSAPP_WEBHOOK_HEADER."""
    return _derive(settings.evolution_api_key, "msgbot-whatsapp-webhook")


def telegram_webhook_secret() -> str:
    """secret_token registered with Telegram (A-Z, a-z, 0-9, _ and - only)."""
    return _derive(settings.telegram_bot_token, "msgbot-telegram-webhook")


def check_secret(received: str | None, expected: str) -> bool:
    return bool(received) and hmac.compare_digest(received.encode(), expected.encode())


# ---- Session cookie: "<expiry>.<hmac(expiry)>" ----
# The signing key is derived from the password, so changing the password logs
# every session out.

def _session_key() -> str:
    return _derive(web_password(), "msgbot-session")


def make_session(now: float | None = None) -> str:
    expiry = str(int((now or time.time()) + SESSION_MAX_AGE))
    return f"{expiry}.{_derive(_session_key(), expiry)}"


def valid_session(value: str | None, now: float | None = None) -> bool:
    if not value or "." not in value:
        return False
    expiry, signature = value.split(".", 1)
    if not expiry.isdigit() or int(expiry) < (now or time.time()):
        return False
    return hmac.compare_digest(signature, _derive(_session_key(), expiry))


def _is_public(path: str) -> bool:
    return path in _PUBLIC_PATHS or path.startswith(_PUBLIC_PREFIXES)


def _same_origin(headers: dict[str, str]) -> bool:
    """False when a browser tells us the request comes from another site.

    Browsers send Sec-Fetch-Site (and Origin) on cross-site requests; clients
    that send neither, like curl, aren't browsers and can't carry a victim's
    cookie, so they are allowed.
    """
    site = headers.get("sec-fetch-site")
    if site is not None:
        return site in ("same-origin", "none")
    origin = headers.get("origin")
    if origin is not None:
        return urlsplit(origin).netloc == headers.get("host", "")
    return True


def _cookie(headers: dict[str, str], name: str) -> str | None:
    for part in headers.get("cookie", "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return None


class AuthMiddleware:
    """ASGI middleware, so it covers WebSockets as well as HTTP."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or _is_public(scope["path"]):
            return await self.app(scope, receive, send)

        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
        authenticated = valid_session(_cookie(headers, SESSION_COOKIE))

        if scope["type"] == "websocket":
            if authenticated and _same_origin(headers):
                return await self.app(scope, receive, send)
            # Reject the handshake: the ASGI server answers 403
            await receive()
            return await send({"type": "websocket.close", "code": 1008})

        if authenticated and (scope["method"] in _SAFE_METHODS or _same_origin(headers)):
            return await self.app(scope, receive, send)

        if authenticated:
            response = HTMLResponse("Cross-site request blocked", status_code=403)
        elif headers.get("hx-request"):
            # htmx follows HX-Redirect instead of swapping the error in
            response = HTMLResponse("Login required", status_code=401,
                                    headers={"HX-Redirect": "/login"})
        elif scope["method"] == "GET" and "text/html" in headers.get("accept", ""):
            path = scope["path"] + ("?" + scope["query_string"].decode() if scope["query_string"] else "")
            response = RedirectResponse(f"/login?next={quote(path)}", status_code=303)
        else:
            response = HTMLResponse("Login required", status_code=401)
        await response(scope, receive, send)


# ---- Login page ----

router = APIRouter()


def _safe_next(target: str) -> str:
    """Only redirect to paths on this site, never to another host."""
    return target if target.startswith("/") and not target.startswith("//") else "/"


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/"):
    from bot.web.routes import templates
    return templates.TemplateResponse(request, "login.html", {"next": _safe_next(next), "error": ""})


@router.post("/login")
async def login(request: Request, username: str = Form(""), password: str = Form(""), next: str = Form("/")):
    from bot.web.routes import templates
    ok = (hmac.compare_digest(username.encode(), settings.web_username.encode())
          & hmac.compare_digest(password.encode(), web_password().encode()))
    if not ok or not _same_origin({k.lower(): v for k, v in request.headers.items()}):
        log.warning("login_failed", username=username, client=request.client.host if request.client else "")
        await asyncio.sleep(1)  # slow down password guessing
        return templates.TemplateResponse(
            request, "login.html",
            {"next": _safe_next(next), "error": "Wrong username or password."},
            status_code=401,
        )
    response = RedirectResponse(_safe_next(next), status_code=303)
    response.set_cookie(
        SESSION_COOKIE, make_session(), max_age=SESSION_MAX_AGE,
        httponly=True, samesite="strict",
        secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https",
    )
    log.info("login", username=username)
    return response


@router.post("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response
