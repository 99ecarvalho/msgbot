# Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>
#
# This file is part of MsgBot. It is free software, licensed under the GNU
# Lesser General Public License v3.0 or later. See COPYING.LESSER and
# COPYING for details.
#
# SPDX-License-Identifier: LGPL-3.0-or-later

"""Evolution API client — WhatsApp instance management and messaging."""
from __future__ import annotations

import base64

import structlog
import httpx

from bot.config import settings

log = structlog.get_logger("services.evolution")


def _headers() -> dict:
    return {"apikey": settings.evolution_api_key, "Content-Type": "application/json"}


def _webhook_headers() -> dict:
    """Headers Evolution API adds to every webhook, so the bot can verify them."""
    from bot.web.auth import WHATSAPP_WEBHOOK_HEADER, whatsapp_webhook_secret
    return {WHATSAPP_WEBHOOK_HEADER: whatsapp_webhook_secret()}


def _base() -> str:
    return settings.evolution_api_url.rstrip("/")


async def create_instance(name: str | None = None) -> dict:
    """Create a new WhatsApp instance (or return existing)."""
    name = name or settings.evolution_instance_name
    url = f"{_base()}/instance/create"
    webhook_url = f"{settings.bot_url}/webhook/whatsapp"
    payload = {
        "instanceName": name,
        "integration": "WHATSAPP-BAILEYS",
        "qrcode": True,
        "webhook": {
            "url": webhook_url,
            "headers": _webhook_headers(),
            "byEvents": False,
            "base64": True,
            "events": [
                "MESSAGES_UPSERT",
                "CONNECTION_UPDATE",
            ],
        },
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json=payload, headers=_headers())
        # 403 with "already in use" = instance exists, that's fine
        if resp.status_code in (403, 409):
            log.info("instance_already_exists", name=name)
            return {"instanceName": name, "status": "existing"}
        resp.raise_for_status()
    result = resp.json()
    log.info("instance_created", name=name)
    return result


async def get_connection_status(name: str | None = None) -> dict:
    """Get connection status for an instance."""
    name = name or settings.evolution_instance_name
    url = f"{_base()}/instance/connectionState/{name}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=_headers())
            resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.warning("connection_status_error", error=str(e))
        return {"state": "unknown", "error": str(e)}


async def get_qr_code(name: str | None = None) -> dict:
    """Fetch QR code for pairing. Returns dict with base64/pairingCode."""
    name = name or settings.evolution_instance_name
    url = f"{_base()}/instance/connect/{name}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=_headers())
            resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.warning("qr_fetch_error", error=str(e))
        return {"error": str(e)}


async def set_webhook(name: str | None = None, webhook_url: str = "") -> dict:
    """Configure webhook URL for an instance."""
    name = name or settings.evolution_instance_name
    url = f"{_base()}/webhook/set/{name}"
    payload = {
        "webhook": {
            "url": webhook_url,
            "headers": _webhook_headers(),
            "enabled": True,
            "webhookByEvents": False,
            "webhookBase64": True,
            "events": [
                "MESSAGES_UPSERT",
                "CONNECTION_UPDATE",
            ],
        },
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload, headers=_headers())
        resp.raise_for_status()
    log.info("webhook_set", name=name, url=webhook_url)
    return resp.json()


async def send_text(to: str, text: str, name: str | None = None) -> dict:
    """Send a text message."""
    name = name or settings.evolution_instance_name
    url = f"{_base()}/message/sendText/{name}"
    payload = {"number": to, "text": text}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json=payload, headers=_headers())
        if resp.status_code >= 400:
            log.error("send_text_failed", status=resp.status_code, body=resp.text, to=to)
        resp.raise_for_status()
    return resp.json()


async def send_audio(to: str, audio_bytes: bytes, name: str | None = None) -> dict:
    """Send an audio message (voice note)."""
    name = name or settings.evolution_instance_name
    url = f"{_base()}/message/sendWhatsAppAudio/{name}"
    b64 = base64.b64encode(audio_bytes).decode()
    payload = {
        "number": to,
        "audio": b64,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=_headers())
        if resp.status_code >= 400:
            log.error("send_audio_failed", status=resp.status_code, body=resp.text, to=to)
        resp.raise_for_status()
    return resp.json()


async def download_media(media_url: str) -> bytes:
    """Download media from a URL (used for incoming audio messages)."""
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        resp = await client.get(media_url)
        resp.raise_for_status()
    return resp.content


async def get_media_base64(message_id: str, name: str | None = None) -> bytes:
    """Get media as base64 from Evolution API by message ID."""
    name = name or settings.evolution_instance_name
    url = f"{_base()}/chat/getBase64FromMediaMessage/{name}"
    payload = {"message": {"key": {"id": message_id}}, "convertToMp4": False}
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload, headers=_headers())
        resp.raise_for_status()
    data = resp.json()
    b64_str = data.get("base64", "")
    return base64.b64decode(b64_str)


async def disconnect_instance(name: str | None = None) -> dict:
    """Disconnect (logout) a WhatsApp instance."""
    name = name or settings.evolution_instance_name
    url = f"{_base()}/instance/logout/{name}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.delete(url, headers=_headers())
        resp.raise_for_status()
    return resp.json()


async def fetch_group_info(group_jid: str, name: str | None = None) -> dict:
    """Fetch group metadata (subject/name) from Evolution API."""
    name = name or settings.evolution_instance_name
    url = f"{_base()}/group/findGroupInfos/{name}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=_headers(), params={"groupJid": group_jid})
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        log.debug("fetch_group_info_failed", group_jid=group_jid, error=str(e))
    return {}


async def health() -> dict:
    """Check Evolution API health."""
    try:
        status = await get_connection_status()
        return {"status": "ok", "connection": status}
    except Exception:
        return {"status": "unreachable"}
