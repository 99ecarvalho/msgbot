"""Telegram bot handler — webhook mode via python-telegram-bot."""
from __future__ import annotations

import io

import structlog
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.config import settings
from bot import db
from bot.engine import TelegramSender, process_message
from bot.services import transcriber
from bot.utils import save_audio

log = structlog.get_logger("handlers.telegram")

_app: Application | None = None


def get_app() -> Application:
    """Get or create the telegram Application (singleton)."""
    global _app
    if _app is None:
        _app = (
            Application.builder()
            .token(settings.telegram_bot_token)
            .build()
        )
        _app.add_handler(CommandHandler("start", _cmd_start))
        _app.add_handler(CommandHandler("help", _cmd_help))
        _app.add_handler(CommandHandler("mode", _cmd_mode))
        _app.add_handler(CommandHandler("prompt", _cmd_prompt))
        _app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, _handle_audio))
        _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_text))
    return _app


def _get_response_mode(chat: dict) -> str:
    return chat.get("response_mode") or settings.response_mode


def _get_system_prompt(chat: dict) -> str:
    return chat.get("system_prompt") or settings.default_system_prompt


# ---- Commands ----

async def _cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await db.get_or_create_chat("telegram", chat_id, display_name=update.effective_user.first_name or "")
    await update.message.reply_text(
        "👋 Voice Bot ready!\n\n"
        "Send me a voice message and I'll respond.\n"
        "Forward audio messages for analysis.\n\n"
        "Commands:\n"
        "/mode voice|text|auto — set response mode\n"
        "/prompt <text> — set custom system prompt\n"
        "/help — show this message"
    )


async def _cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _cmd_start(update, context)


async def _cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    chat = await db.get_or_create_chat("telegram", chat_id)
    args = context.args
    if not args or args[0] not in ("voice", "text", "auto"):
        current = _get_response_mode(chat)
        await update.message.reply_text(f"Current mode: {current}\nUsage: /mode voice|text|auto")
        return
    mode = args[0]
    await db.update_chat(chat["id"], response_mode=mode)
    await update.message.reply_text(f"Response mode set to: {mode}")


async def _cmd_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    chat = await db.get_or_create_chat("telegram", chat_id)
    text = update.message.text.replace("/prompt", "", 1).strip()
    if not text:
        current = _get_system_prompt(chat)
        await update.message.reply_text(f"Current prompt:\n{current}\n\nUsage: /prompt <your system prompt>")
        return
    await db.update_chat(chat["id"], system_prompt=text)
    await update.message.reply_text(f"System prompt updated ({len(text)} chars)")


# ---- Audio handling ----

async def _handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice messages and audio files (including forwarded)."""
    if update.effective_user and update.effective_user.id == context.bot.id:
        return

    chat_id = str(update.effective_chat.id)
    display_name = update.effective_user.first_name or ""
    chat = await db.get_or_create_chat("telegram", chat_id, display_name=display_name)
    msg = update.message
    is_forwarded = msg.forward_date is not None

    # Download the audio file
    if msg.voice:
        file = await msg.voice.get_file()
    elif msg.audio:
        file = await msg.audio.get_file()
    else:
        await msg.reply_text("Unsupported audio format.")
        return

    audio_buf = io.BytesIO()
    await file.download_to_memory(audio_buf)
    audio_bytes = audio_buf.getvalue()

    ext = "ogg"
    if msg.audio and msg.audio.mime_type:
        ext = msg.audio.mime_type.split("/")[-1].split(";")[0]

    audio_path = await save_audio(chat_id, "in", audio_bytes, ext)

    # Auto-transcribe (local Whisper, no cost)
    transcription = ""
    try:
        result = await transcriber.transcribe(audio_bytes, filename="audio.ogg", language=None)
        transcription = result.get("text", "").strip()
    except Exception as e:
        log.error("auto_transcribe_failed", chat_id=chat_id, error=str(e))

    # Whitelist check
    tg_is_group = update.effective_chat.type in ("group", "supergroup")
    wl_entry = await db.is_whitelisted("telegram", chat_id, is_group=tg_is_group)
    if not wl_entry:
        await db.save_message(
            chat["id"], "in", "voice",
            audio_path=audio_path,
            content_text="",
            transcription=transcription,
            blocked=True,
        )
        await db.save_log("info", f"Blocked audio from {display_name} ({chat_id}) — not whitelisted", source="telegram")
        log.info("telegram_blocked", chat_id=chat_id, display_name=display_name, reason="not_whitelisted")
        return

    await msg.reply_chat_action("typing")

    # Delegate to workflow engine
    sender = TelegramSender(msg)
    await process_message(
        chat=chat, platform="telegram", phone=chat_id,
        push_name=display_name, sender_phone="",
        sender=sender, whitelist_entry=wl_entry,
        audio_bytes=audio_bytes, audio_path=audio_path,
        msg_type="voice", is_forwarded=is_forwarded,
        is_ptt=msg.voice is not None,
    )


async def _handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plain text messages — delegate to workflow engine."""
    if update.effective_user and update.effective_user.id == context.bot.id:
        return

    chat_id = str(update.effective_chat.id)
    display_name = update.effective_user.first_name or ""
    chat = await db.get_or_create_chat("telegram", chat_id, display_name=display_name)
    text = update.message.text.strip()
    if not text:
        return

    # Whitelist check
    tg_is_group = update.effective_chat.type in ("group", "supergroup")
    wl_entry = await db.is_whitelisted("telegram", chat_id, is_group=tg_is_group)
    if not wl_entry:
        await db.save_message(chat["id"], "in", "text", content_text=text, blocked=True)
        await db.save_log("info", f"Blocked text from {display_name} ({chat_id}) — not whitelisted", source="telegram")
        log.info("telegram_blocked", chat_id=chat_id, display_name=display_name, reason="not_whitelisted")
        return

    await update.message.reply_chat_action("typing")

    # Delegate to workflow engine
    sender = TelegramSender(update.message)
    await process_message(
        chat=chat, platform="telegram", phone=chat_id,
        push_name=display_name, sender_phone="",
        sender=sender, whitelist_entry=wl_entry,
        text=text, msg_type="text",
    )
