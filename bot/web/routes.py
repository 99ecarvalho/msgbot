"""Web UI routes — dashboard, QR, messages, config, logs."""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import structlog
from fastapi import APIRouter, Request, WebSocket, Form
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from bot.config import settings
from bot import db
from bot.services import transcriber as transcriber_svc
from bot.services import tts as tts_svc
from bot.services import evolution as evolution_svc
from bot.utils import save_audio, convert_wav_to_ogg_opus
from bot.web.ws import ws_logs, ws_qr

log = structlog.get_logger("web.routes")

router = APIRouter()

templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


def _ts_to_str(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


# Register template global
templates.env.globals["ts_to_str"] = _ts_to_str
templates.env.globals["now"] = lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---- Dashboard ----

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    # Service health checks (parallel)
    import asyncio
    t_health, tts_health, evo_health = await asyncio.gather(
        transcriber_svc.health(),
        tts_svc.health(),
        evolution_svc.health(),
    )

    # Stats
    all_msgs = await db.get_messages(limit=10)
    all_chats = await db.get_all_chats()

    tg_ok = bool(settings.telegram_bot_token)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "transcriber_health": t_health,
        "tts_health": tts_health,
        "evolution_health": evo_health,
        "telegram_configured": tg_ok,
        "recent_messages": all_msgs,
        "total_chats": len(all_chats),
    })


# ---- QR Code ----

@router.get("/qr", response_class=HTMLResponse)
async def qr_page(request: Request):
    # Ensure instance exists
    try:
        await evolution_svc.create_instance()
    except Exception as e:
        log.warning("qr_page_create_instance_failed", error=str(e))
    status = await evolution_svc.get_connection_status()
    return templates.TemplateResponse("qr.html", {
        "request": request,
        "initial_status": status,
    })


@router.post("/qr/disconnect")
async def qr_disconnect():
    await evolution_svc.disconnect_instance()
    return RedirectResponse("/qr", status_code=303)


@router.post("/qr/reconnect")
async def qr_reconnect():
    await evolution_svc.create_instance()
    return RedirectResponse("/qr", status_code=303)


# ---- Messages ----

@router.get("/messages", response_class=HTMLResponse)
async def messages_page(request: Request, platform: str = "", chat_id: str = "", limit: int = 50, whitelisted: str = ""):
    chats = await db.get_all_chats()

    chat_rowid = None
    if chat_id:
        for c in chats:
            if c["chat_id"] == chat_id and (not platform or c["platform"] == platform):
                chat_rowid = c["id"]
                break

    msgs = await db.get_messages(chat_rowid=chat_rowid, limit=limit)

    # Optional filter: exclude blocked messages
    if whitelisted == "1":
        msgs = [m for m in msgs if "[BLOCKED" not in (m.get("content_text") or "")]

    return templates.TemplateResponse("messages.html", {
        "request": request,
        "messages": msgs,
        "chats": chats,
        "filter_platform": platform,
        "filter_chat_id": chat_id,
        "filter_whitelisted": whitelisted,
    })


@router.get("/messages/{chat_rowid}", response_class=HTMLResponse)
async def chat_thread(request: Request, chat_rowid: int):
    msgs = await db.get_messages(chat_rowid=chat_rowid, limit=200)
    chats = await db.get_all_chats()
    chat_info = next((c for c in chats if c["id"] == chat_rowid), None)

    return templates.TemplateResponse("messages.html", {
        "request": request,
        "messages": msgs,
        "chats": chats,
        "chat_info": chat_info,
        "filter_platform": "",
        "filter_chat_id": "",
    })


# ---- Config ----

@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    cfg = await db.get_all_config()
    chats = await db.get_all_chats()
    whitelist = await db.get_whitelist()

    return templates.TemplateResponse("config.html", {
        "request": request,
        "config": cfg,
        "chats": chats,
        "whitelist": whitelist,
        "defaults": {
            "default_system_prompt": settings.default_system_prompt,
            "response_mode": settings.response_mode,
            "azure_deployment": settings.azure_openai_deployment_name,
        },
    })


@router.post("/config")
async def save_config(
    request: Request,
    default_system_prompt: str = Form(""),
    response_mode: str = Form("auto"),
    azure_deployment: str = Form("gpt-4.1"),
):
    await db.set_config("default_system_prompt", default_system_prompt)
    await db.set_config("response_mode", response_mode)
    await db.set_config("azure_deployment", azure_deployment)

    # Update runtime settings
    settings.default_system_prompt = default_system_prompt
    settings.response_mode = response_mode
    settings.azure_openai_deployment_name = azure_deployment

    if request.headers.get("HX-Request"):
        return HTMLResponse('<div class="notice">Configuration saved.</div>')
    return RedirectResponse("/config", status_code=303)


@router.post("/config/chats/{chat_rowid}")
async def save_chat_config(
    request: Request,
    chat_rowid: int,
    system_prompt: str = Form(""),
    response_mode: str = Form(""),
):
    await db.update_chat(chat_rowid, system_prompt=system_prompt, response_mode=response_mode)

    if request.headers.get("HX-Request"):
        return HTMLResponse('<span class="notice">Saved</span>')
    return RedirectResponse("/config", status_code=303)


# ---- Whitelist ----

@router.get("/config/whitelist", response_class=HTMLResponse)
async def whitelist_fragment(request: Request):
    """HTMX fragment returning just the whitelist table rows."""
    entries = await db.get_whitelist()
    return templates.TemplateResponse("_whitelist_rows.html", {
        "request": request,
        "whitelist": entries,
    })


@router.post("/config/whitelist")
async def add_whitelist(
    request: Request,
    filter_type: str = Form(...),
    value: str = Form(...),
    platform: str = Form(""),
    notes: str = Form(""),
):
    value = value.strip()
    if not value:
        return HTMLResponse("Value is required", status_code=400)
    await db.add_whitelist_entry(filter_type=filter_type, value=value, platform=platform, notes=notes)

    # If called from messages page (HX-Target is wl-toast), return a toast
    hx_target = request.headers.get("HX-Target", "")
    if hx_target == "wl-toast":
        return HTMLResponse(f'<div class="notice">{value} added to whitelist</div>')

    # Return updated list for config page
    entries = await db.get_whitelist()
    return templates.TemplateResponse("_whitelist_rows.html", {
        "request": request,
        "whitelist": entries,
    })


@router.post("/messages/whitelist-quick")
async def quick_whitelist(request: Request):
    """Quick-add a phone from the messages page to the whitelist."""
    form = await request.form()
    phone = form.get("phone", "").strip()
    platform = form.get("platform", "whatsapp")
    display_name = form.get("display_name", "")

    if not phone:
        return HTMLResponse("Phone is required", status_code=400)

    # Check if already whitelisted
    existing = await db.get_whitelist()
    for e in existing:
        if e["filter_type"] == "phone" and e["value"] == phone:
            return HTMLResponse(f'<span class="notice">{phone} already whitelisted</span>')

    await db.add_whitelist_entry(
        filter_type="phone",
        value=phone,
        platform=platform,
        notes=f"Quick-added from messages ({display_name})" if display_name else "Quick-added from messages",
    )
    return HTMLResponse(f'<span class="notice">{phone} whitelisted</span>')


@router.delete("/config/whitelist/{entry_id}")
async def delete_whitelist(request: Request, entry_id: int):
    await db.remove_whitelist_entry(entry_id)
    entries = await db.get_whitelist()
    return templates.TemplateResponse("_whitelist_rows.html", {
        "request": request,
        "whitelist": entries,
    })


@router.post("/config/whitelist/{entry_id}/toggle")
async def toggle_whitelist(request: Request, entry_id: int):
    entries = await db.get_whitelist()
    current = next((e for e in entries if e["id"] == entry_id), None)
    if current:
        await db.toggle_whitelist_entry(entry_id, not current["enabled"])
    entries = await db.get_whitelist()
    return templates.TemplateResponse("_whitelist_rows.html", {
        "request": request,
        "whitelist": entries,
    })


# ---- Logs ----

@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    return templates.TemplateResponse("logs.html", {"request": request})


# ---- Database maintenance ----

@router.post("/config/clear/{target}")
async def clear_data(request: Request, target: str):
    valid = {"messages", "logs", "chats", "whitelist", "config", "all"}
    if target not in valid:
        return HTMLResponse("Invalid target", status_code=400)

    fn = getattr(db, f"clear_{target}", None)
    if fn:
        await fn()
        await db.save_log("warning", f"Cleared {target} data", source="web")

    if request.headers.get("HX-Request"):
        return HTMLResponse(f'<div class="notice">{target.capitalize()} data cleared.</div>')
    return RedirectResponse("/config", status_code=303)


# ---- Statistics ----

@router.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    stats = await db.get_stats()
    return templates.TemplateResponse("stats.html", {
        "request": request,
        "stats": stats,
    })


# ---- Tools (Whisper & TTS testing) ----

@router.get("/tools", response_class=HTMLResponse)
async def tools_page(request: Request):
    import asyncio
    t_health, tts_health = await asyncio.gather(
        transcriber_svc.health(),
        tts_svc.health(),
    )
    return templates.TemplateResponse("tools.html", {
        "request": request,
        "transcriber_health": t_health,
        "tts_health": tts_health,
    })


@router.post("/tools/transcribe")
async def tools_transcribe(request: Request):
    from fastapi.responses import JSONResponse
    form = await request.form()
    file = form.get("file")
    language = form.get("language", "")

    if not file or not hasattr(file, "read"):
        return JSONResponse({"error": "No audio file provided"}, status_code=400)

    audio_bytes = await file.read()
    if not audio_bytes:
        return JSONResponse({"error": "Empty audio file"}, status_code=400)

    try:
        result = await transcriber_svc.transcribe(
            audio_bytes,
            filename=file.filename or "audio.webm",
            language=language or None,
        )
        return JSONResponse(result)
    except Exception as e:
        log.error("tools.transcribe_failed", error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/tools/tts")
async def tools_tts(request: Request):
    from fastapi.responses import JSONResponse, Response
    body = await request.json()
    text = body.get("text", "").strip()

    if not text:
        return JSONResponse({"error": "No text provided"}, status_code=400)

    if len(text) > 5000:
        return JSONResponse({"error": "Text too long (max 5000 chars)"}, status_code=400)

    try:
        audio_bytes = await tts_svc.synthesize(text)
        return Response(content=audio_bytes, media_type="audio/wav")
    except Exception as e:
        log.error("tools.tts_failed", error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)


# ---- Reply from Web UI ----

@router.post("/messages/reply")
async def reply_message(request: Request):
    """Send a reply to a WhatsApp chat from the web UI."""
    from fastapi.responses import JSONResponse

    form = await request.form()
    chat_id = form.get("chat_id", "").strip()
    platform = form.get("platform", "whatsapp")
    mode = form.get("mode", "text")  # "text" or "voice"
    text = form.get("text", "").strip()
    chat_rowid = int(form.get("chat_rowid", 0))

    if not chat_id or not text:
        return JSONResponse({"error": "chat_id and text are required"}, status_code=400)

    if platform != "whatsapp":
        return JSONResponse({"error": "Only WhatsApp replies are supported"}, status_code=400)

    try:
        out_audio_path = ""
        if mode == "voice":
            # Synthesize text to speech, convert to ogg, send both text and audio
            wav_bytes = await tts_svc.synthesize(text)
            ogg_bytes = await convert_wav_to_ogg_opus(wav_bytes)
            out_audio_path = await save_audio(chat_id, "out", ogg_bytes, "ogg")
            await evolution_svc.send_text(chat_id, text)
            await evolution_svc.send_audio(chat_id, ogg_bytes)
        else:
            await evolution_svc.send_text(chat_id, text)

        # Save outgoing message to DB
        if chat_rowid:
            await db.save_message(
                chat_rowid, "out",
                "voice" if mode == "voice" else "text",
                content_text=text,
                audio_path=out_audio_path,
            )

        await db.save_log("info", f"Web reply to {chat_id}: {text[:80]}", source="web")
        return JSONResponse({"ok": True, "mode": mode})

    except Exception as e:
        log.error("web_reply_failed", error=str(e), chat_id=chat_id)
        return JSONResponse({"error": str(e)}, status_code=500)


# ---- Audio file serving ----

@router.get("/audios/{path:path}")
async def serve_audio(path: str):
    file_path = settings.data_dir / path
    if not file_path.exists() or not file_path.is_file():
        return HTMLResponse("Not found", status_code=404)
    # Prevent path traversal
    try:
        file_path.resolve().relative_to(settings.data_dir.resolve())
    except ValueError:
        return HTMLResponse("Forbidden", status_code=403)
    media = "audio/ogg"
    if file_path.suffix == ".wav":
        media = "audio/wav"
    elif file_path.suffix == ".mp3":
        media = "audio/mpeg"
    return FileResponse(str(file_path), media_type=media)


# ---- WebSocket routes ----

@router.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await ws_logs(websocket)


@router.websocket("/ws/qr")
async def websocket_qr(websocket: WebSocket):
    await ws_qr(websocket)
