# Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>
#
# This file is part of MsgBot. It is free software, licensed under the GNU
# Lesser General Public License v3.0 or later. See COPYING.LESSER and
# COPYING for details.
#
# SPDX-License-Identifier: LGPL-3.0-or-later

"""WhatsApp handler — receives webhooks from Evolution API."""
from __future__ import annotations

import base64
import io

import structlog

from bot.config import settings
from bot import db
from bot.engine import WhatsAppSender, process_message
from bot.services import evolution
from bot.services import transcriber
from bot.utils import save_audio

log = structlog.get_logger("handlers.whatsapp")


def _detect_device(message_id: str, source: str = "") -> str:
    """Detect sender device.

    Prefers the 'source' field from Evolution API payload (web, android, ios, etc.).
    Falls back to message ID pattern heuristics (Baileys convention).
    """
    # Evolution API provides the actual device in the 'source' field
    if source:
        s = source.lower()
        if s in ("android", "ios", "web", "desktop"):
            return s
        if "iphone" in s or "ipad" in s:
            return "ios"
    # Fallback: infer from message ID pattern
    if not message_id:
        return ""
    if message_id.startswith("3EB0"):
        return "android"
    if message_id.startswith("BAE5"):
        return "web"
    if len(message_id) >= 20 and message_id.isupper() and message_id.isalnum():
        return "ios"
    return ""


def _get_response_mode(chat: dict) -> str:
    return chat.get("response_mode") or settings.response_mode


def _get_system_prompt(chat: dict) -> str:
    return chat.get("system_prompt") or settings.default_system_prompt


async def handle_webhook(payload: dict):
    """Process an incoming Evolution API webhook event."""
    event = payload.get("event")

    if event == "messages.upsert":
        await _handle_messages_upsert(payload)
    elif event == "connection.update":
        data = payload.get("data", {})
        state = data.get("state", "")
        if state in ("open", "close"):
            log.info("whatsapp_connection_update", data=data)
        else:
            log.debug("whatsapp_connection_update", data=data)
    else:
        log.debug("whatsapp_unhandled_event", event=event)


async def _handle_messages_upsert(payload: dict):
    """Handle incoming messages from WhatsApp."""
    data = payload.get("data", {})

    # Skip status/protocol messages
    if data.get("messageType") in ("protocolMessage", "reactionMessage"):
        return

    key = data.get("key", {})
    if key.get("fromMe"):
        log.debug("skipping_own_message", reason="fromMe")
        return  # Skip our own messages

    # In groups, also check participant — if it matches the bot's own JID, skip
    participant = key.get("participant") or ""
    instance_jid = data.get("instance", {}).get("wuid", "")
    if participant and instance_jid and participant == instance_jid:
        log.debug("skipping_own_message", reason="participant_matches_instance")
        return  # Skip bot's own messages in groups

    # Skip pure status updates (no message content)
    msg_content = data.get("message", {})
    if not msg_content:
        return

    remote_jid = key.get("remoteJid", "")
    if not remote_jid:
        return

    # Extract phone number from JID (strip @s.whatsapp.net)
    phone = remote_jid.split("@")[0]
    push_name = data.get("pushName", "")

    # Check if this is a group message
    is_group = remote_jid.endswith("@g.us")
    group_name = ""
    sender_phone = ""

    if is_group:
        # For groups: group_name comes from Evolution API webhook data
        group_name = data.get("groupName", "") or data.get("groupSubject", "")
        # Use participant JID as sender identifier (may be @lid or @s.whatsapp.net)
        if participant:
            sender_phone = participant.split("@")[0]

    else:
        # For DMs: sender phone = phone extracted from remoteJid
        sender_phone = phone

    chat = await db.get_or_create_chat(
        "whatsapp", phone,
        display_name=group_name if is_group else push_name,
        group_name=group_name, is_group=is_group,
    )

    # If webhook didn't include group name, try fetching from Evolution API
    if is_group and not chat.get("group_name"):
        try:
            info = await evolution.fetch_group_info(remote_jid)
            fetched_name = info.get("subject", "")
            if fetched_name:
                group_name = fetched_name
                await db.update_chat(chat["id"], group_name=fetched_name, display_name=fetched_name)
                chat["group_name"] = fetched_name
                chat["display_name"] = fetched_name
        except Exception:
            pass

    message = data.get("message", {})
    message_type = data.get("messageType", "")
    message_id = key.get("id", "")
    device = _detect_device(message_id, source=data.get("source", ""))

    # Handle audio/voice messages
    if message_type in ("audioMessage", "pttMessage") or "audioMessage" in message:
        await _handle_audio_message(chat, phone, push_name, sender_phone, group_name, data, message_id, device, remote_jid)
        return

    # Handle text messages (including commands)
    text = ""
    if "conversation" in message:
        text = message["conversation"]
    elif "extendedTextMessage" in message:
        text = message["extendedTextMessage"].get("text", "")

    if text:
        await _handle_text_message(chat, phone, push_name, sender_phone, group_name, text, device, remote_jid)


async def _handle_audio_message(chat: dict, phone: str, push_name: str, sender_phone: str, group_name: str, data: dict, message_id: str, device: str = "", remote_jid: str = ""):
    """Process incoming audio/voice message."""
    is_ptt = data.get("messageType") == "pttMessage"

    # Download media via Evolution API
    try:
        audio_bytes = await evolution.get_media_base64(message_id)
    except Exception as e:
        log.error("whatsapp_media_download_failed", error=str(e), message_id=message_id)
        return

    if not audio_bytes:
        return

    # Save incoming audio (log everything regardless of whitelist)
    audio_path = await save_audio(phone, "in", audio_bytes, "ogg")

    # Auto-transcribe (local Whisper, no cost)
    transcription = ""
    try:
        result = await transcriber.transcribe(audio_bytes, filename="audio.ogg", language=None)
        transcription = result.get("text", "").strip()
    except Exception as e:
        log.error("auto_transcribe_failed", phone=phone, error=str(e))

    # Whitelist check
    is_group = remote_jid.endswith("@g.us")
    wl_entry = await db.is_whitelisted("whatsapp", phone, is_group=is_group, sender_phone=sender_phone)
    if not wl_entry:
        await db.save_message(
            chat["id"], "in", "voice",
            audio_path=audio_path,
            content_text="",
            transcription=transcription,
            sender_name=push_name, sender_phone=sender_phone,
            device=device, blocked=True,
        )
        await db.save_log("info", f"Blocked audio from {push_name} ({phone}) [{sender_phone}] device={device} — not whitelisted", source="whatsapp")
        log.info("whatsapp_blocked", phone=phone, push_name=push_name, reason="not_whitelisted")
        return

    is_forwarded = data.get("message", {}).get("audioMessage", {}).get("contextInfo", {}).get("isForwarded", False)

    # Delegate to workflow engine
    sender = WhatsAppSender(remote_jid or phone)
    await process_message(
        chat=chat, platform="whatsapp", phone=phone,
        push_name=push_name, sender_phone=sender_phone,
        sender=sender, whitelist_entry=wl_entry,
        audio_bytes=audio_bytes, audio_path=audio_path,
        msg_type="voice", is_forwarded=is_forwarded, is_ptt=is_ptt,
        device=device,
    )


async def _handle_text_message(chat: dict, phone: str, push_name: str, sender_phone: str, group_name: str, text: str, device: str = "", remote_jid: str = ""):
    """Handle incoming text messages (including commands)."""
    text = text.strip()
    if not text:
        return

    # Whitelist check
    is_group = remote_jid.endswith("@g.us")
    wl_entry = await db.is_whitelisted("whatsapp", phone, is_group=is_group, sender_phone=sender_phone)
    if not wl_entry:
        await db.save_message(chat["id"], "in", "text", content_text=text,
                              sender_name=push_name, sender_phone=sender_phone,
                              device=device, blocked=True)
        await db.save_log("info", f"Blocked text from {push_name} ({phone}) [{sender_phone}] device={device} — not whitelisted", source="whatsapp")
        log.info("whatsapp_blocked", phone=phone, push_name=push_name, reason="not_whitelisted")
        return

    # Commands (handled directly, not through workflows)
    if text.startswith("/mode"):
        parts = text.split(maxsplit=1)
        if len(parts) > 1 and parts[1] in ("voice", "text", "auto"):
            await db.update_chat(chat["id"], response_mode=parts[1])
            await evolution.send_text(phone, f"Response mode set to: {parts[1]}")
        else:
            current = _get_response_mode(chat)
            await evolution.send_text(phone, f"Current mode: {current}\nUsage: /mode voice|text|auto")
        return

    if text.startswith("/prompt"):
        prompt_text = text.replace("/prompt", "", 1).strip()
        if prompt_text:
            await db.update_chat(chat["id"], system_prompt=prompt_text)
            await evolution.send_text(phone, f"System prompt updated ({len(prompt_text)} chars)")
        else:
            current = _get_system_prompt(chat)
            await evolution.send_text(phone, f"Current prompt:\n{current}\n\nUsage: /prompt <your system prompt>")
        return

    if text.startswith(("/help", "/start")):
        await evolution.send_text(
            phone,
            "👋 Voice Bot ready!\n\n"
            "Send me a voice message and I'll respond.\n"
            "Forward audio messages for analysis.\n\n"
            "Commands:\n"
            "/mode voice|text|auto — set response mode\n"
            "/prompt <text> — set custom system prompt\n"
            "/help — show this message"
        )
        return

    # Regular text — delegate to workflow engine
    sender = WhatsAppSender(remote_jid or phone)
    await process_message(
        chat=chat, platform="whatsapp", phone=phone,
        push_name=push_name, sender_phone=sender_phone,
        sender=sender, whitelist_entry=wl_entry,
        text=text, msg_type="text",
        device=device,
    )
