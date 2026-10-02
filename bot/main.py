# Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>
#
# This file is part of MsgBot. It is free software, licensed under the GNU
# Lesser General Public License v3.0 or later. See COPYING.LESSER and
# COPYING for details.
#
# SPDX-License-Identifier: LGPL-3.0-or-later

"""Main FastAPI application — webhooks, web UI, startup lifecycle."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from bot.config import settings
from bot import db
from bot.handlers.telegram import get_app as get_telegram_app
from bot.handlers.whatsapp import handle_webhook as handle_wa_webhook
from bot.services import evolution
from bot.web import auth
from bot.web.routes import router as web_router

log = structlog.get_logger("main")

# Track background tasks to prevent GC
_background_tasks: set = set()


def _task_done(task: asyncio.Task):
    """Log exceptions from background webhook tasks."""
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        log.error("background_task_failed", error=str(exc), exc_info=exc)

# Configure structlog
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),
    logger_factory=structlog.PrintLoggerFactory(),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    log.info("bot.starting")

    # Init database
    await db.get_db()
    log.info("database.ready", path=str(settings.db_path))

    # Ensure data dirs exist
    settings.audios_dir.mkdir(parents=True, exist_ok=True)

    # Initialize default config if not set
    if not await db.get_config("default_system_prompt"):
        await db.set_config("default_system_prompt", settings.default_system_prompt)
    if not await db.get_config("response_mode"):
        await db.set_config("response_mode", settings.response_mode)
    if not await db.get_config("azure_deployment"):
        await db.set_config("azure_deployment", settings.azure_openai_deployment_name)

    # Setup Telegram webhook
    if settings.telegram_bot_token:
        try:
            tg_app = get_telegram_app()
            await tg_app.initialize()
            webhook_url = f"{settings.bot_url}/webhook/telegram"
            await tg_app.bot.set_webhook(webhook_url, secret_token=auth.telegram_webhook_secret())
            log.info("telegram.webhook_set", url=webhook_url)
        except Exception as e:
            log.error("telegram.setup_failed", error=str(e))

    # Setup Evolution API instance + webhook
    if settings.evolution_api_key:
        try:
            await evolution.create_instance()
            webhook_url = f"{settings.bot_url}/webhook/whatsapp"
            await evolution.set_webhook(webhook_url=webhook_url)
            log.info("evolution.webhook_set", url=webhook_url)
        except Exception as e:
            log.error("evolution.setup_failed", error=str(e))

    auth.web_password()  # logs the generated password when WEB_PASSWORD is unset
    await db.save_log("info", "Bot started", source="main")
    log.info("bot.ready")

    yield

    # Shutdown
    if settings.telegram_bot_token:
        try:
            tg_app = get_telegram_app()
            await tg_app.shutdown()
        except Exception:
            pass
    await db.close_db()
    log.info("bot.stopped")


app = FastAPI(title="MsgBot", version="0.1.0", lifespan=lifespan)

# Mount static files
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Web UI login; webhooks and static files stay public
app.add_middleware(auth.AuthMiddleware)
app.include_router(auth.router)

# Mount web UI routes
app.include_router(web_router)


# ---- Webhook endpoints ----

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """Receive Telegram updates."""
    if not settings.telegram_bot_token or not auth.check_secret(
            request.headers.get(auth.TELEGRAM_SECRET_HEADER), auth.telegram_webhook_secret()):
        log.warning("telegram.webhook_rejected", client=request.client.host if request.client else "")
        return JSONResponse({"ok": False}, status_code=403)
    data = await request.json()
    tg_app = get_telegram_app()
    from telegram import Update
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    """Receive Evolution API webhook events."""
    if not settings.evolution_api_key or not auth.check_secret(
            request.headers.get(auth.WHATSAPP_WEBHOOK_HEADER), auth.whatsapp_webhook_secret()):
        log.warning("whatsapp.webhook_rejected", client=request.client.host if request.client else "")
        return JSONResponse({"ok": False}, status_code=403)
    data = await request.json()
    task = asyncio.create_task(handle_wa_webhook(data))
    _background_tasks.add(task)
    task.add_done_callback(_task_done)
    return {"ok": True}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "msgbot"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
