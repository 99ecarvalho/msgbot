# Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>
#
# This file is part of MsgBot. It is free software, licensed under the GNU
# Lesser General Public License v3.0 or later. See COPYING.LESSER and
# COPYING for details.
#
# SPDX-License-Identifier: LGPL-3.0-or-later

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

from markupsafe import Markup

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


def _is_phone(digits: str) -> bool:
    """Check if a digit string looks like a real phone number (not a WhatsApp LID)."""
    return digits.isdigit() and 10 <= len(digits) <= 13


def _format_phone(value: str) -> Markup:
    """Convert WhatsApp JID to human-readable phone or short ID."""
    if not value:
        return Markup("")
    # Strip @s.whatsapp.net → phone number
    if "@s.whatsapp.net" in value:
        digits = value.split("@")[0]
    elif "@g.us" in value:
        return Markup(value.split("@")[0])
    else:
        digits = value.lstrip("+")

    # Brazilian numbers: 55 + 2-digit area + 8-9 digit number
    if digits.startswith("55") and len(digits) in (12, 13):
        area = digits[2:4]
        number = digits[4:]
        if len(number) == 9:
            formatted = f"{number[:5]}-{number[5:]}"
        else:
            formatted = f"{number[:4]}-{number[4:]}"
        return Markup(
            f'<span class="phone-country">+55</span> {area} {formatted}'
        )

    # Plausible phone numbers (10-13 digits): format with +
    if _is_phone(digits):
        # Try generic formatting: +CC rest
        if len(digits) >= 11:
            cc = digits[:2]
            rest = digits[2:]
            return Markup(f'<span class="phone-country">+{cc}</span> {rest}')
        return Markup(f"+{digits}")

    # LIDs / non-phone identifiers (14+ digits): show as short ID
    if len(digits) > 13 and digits.isdigit():
        return Markup(f'<span class="phone-lid">{digits}</span>')

    return Markup(digits)


def _format_phone_plain(value: str) -> str:
    """Plain-text phone formatting (for <option> elements, no HTML)."""
    if not value:
        return ""
    if "@s.whatsapp.net" in value:
        digits = value.split("@")[0]
    elif "@g.us" in value:
        return value.split("@")[0]
    else:
        digits = value.lstrip("+")

    if digits.startswith("55") and len(digits) in (12, 13):
        area = digits[2:4]
        number = digits[4:]
        if len(number) == 9:
            formatted = f"{number[:5]}-{number[5:]}"
        else:
            formatted = f"{number[:4]}-{number[4:]}"
        return f"+55 {area} {formatted}"

    # Only add + for plausible phone numbers (max 13 digits)
    if _is_phone(digits):
        return f"+{digits}"

    return digits


templates.env.filters["format_phone"] = _format_phone
templates.env.globals["format_phone"] = _format_phone
templates.env.filters["format_phone_plain"] = _format_phone_plain
templates.env.globals["format_phone_plain"] = _format_phone_plain
templates.env.globals["is_phone"] = lambda v: _is_phone(v.split("@")[0] if "@" in v else v.lstrip("+"))


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
    stats = await db.get_stats()

    tg_ok = bool(settings.telegram_bot_token)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "transcriber_health": t_health,
        "tts_health": tts_health,
        "evolution_health": evo_health,
        "telegram_configured": tg_ok,
        "recent_messages": all_msgs,
        "total_chats": len(all_chats),
        "stats": stats,
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
async def messages_page(request: Request, platform: str = "", chat_id: str = "", sender: str = "", limit: int = 50, whitelisted: str = ""):
    chats = await db.get_all_chats()

    chat_rowid = None
    if chat_id:
        for c in chats:
            if c["chat_id"] == chat_id and (not platform or c["platform"] == platform):
                chat_rowid = c["id"]
                break

    msgs = await db.get_messages(chat_rowid=chat_rowid, limit=limit)

    # Filter by platform if set (and no specific chat selected)
    if platform and not chat_rowid:
        msgs = [m for m in msgs if m.get("platform") == platform]

    # Filter by sender phone/ID
    if sender:
        msgs = [m for m in msgs if m.get("sender_phone") == sender or m.get("effective_phone") == sender]

    # Optional filter: exclude blocked messages
    if whitelisted == "1":
        msgs = [m for m in msgs if not m.get("blocked")]

    # Enrich messages with whitelist status
    wl_entries = await db.get_whitelist()
    for msg in msgs:
        msg["wl_person"] = None
        msg["wl_group"] = None
        msg["wl_person_in_group"] = None
        if msg.get("direction") != "in":
            continue
        for e in wl_entries:
            if not e.get("enabled"):
                continue
            if e.get("platform") and e["platform"] != msg.get("platform"):
                continue
            et = e.get("entry_type") or e.get("filter_type", "")
            sp = msg.get("sender_phone", "") or msg.get("effective_phone", "")
            cid = msg.get("chat_id", "")
            if et == "person" and e.get("phone") in (sp, cid) and sp:
                msg["wl_person"] = e
            elif et == "group" and msg.get("is_group") and e.get("group_id") == cid:
                msg["wl_group"] = e
            elif et == "person_in_group" and msg.get("is_group") and e.get("group_id") == cid and e.get("phone") == sp and sp:
                msg["wl_person_in_group"] = e

    return templates.TemplateResponse("messages.html", {
        "request": request,
        "messages": msgs,
        "chats": chats,
        "filter_platform": platform,
        "filter_chat_id": chat_id,
        "filter_sender": sender,
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

    return templates.TemplateResponse("config.html", {
        "request": request,
        "config": cfg,
        "chats": chats,
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

@router.get("/whitelist", response_class=HTMLResponse)
async def whitelist_page(request: Request):
    """Whitelist management page."""
    entries = await db.get_whitelist()
    chats = await db.get_all_chats()
    groups = [c for c in chats if c.get("is_group")]
    all_workflows = await db.get_all_workflows()
    # Enrich entries with group display names and workflow links
    group_names = {c["chat_id"]: c.get("group_name") or c.get("display_name") or c["chat_id"] for c in groups}
    for e in entries:
        gid = e.get("group_id", "")
        e["group_display_name"] = group_names.get(gid, gid) if gid else ""
        linked = await db.get_workflows_for_whitelist_entry(e["id"])
        e["workflow_ids"] = [w["id"] for w in linked]
    return templates.TemplateResponse("whitelist.html", {
        "request": request,
        "whitelist": entries,
        "groups": groups,
        "workflows": all_workflows,
    })


async def _enriched_whitelist(request: Request):
    """Helper: return enriched whitelist fragment."""
    entries = await db.get_whitelist()
    chats = await db.get_all_chats()
    all_workflows = await db.get_all_workflows()
    group_names = {c["chat_id"]: c.get("group_name") or c.get("display_name") or c["chat_id"] for c in chats if c.get("is_group")}
    for e in entries:
        gid = e.get("group_id", "")
        e["group_display_name"] = group_names.get(gid, gid) if gid else ""
        linked = await db.get_workflows_for_whitelist_entry(e["id"])
        e["workflow_ids"] = [w["id"] for w in linked]
    return templates.TemplateResponse("_whitelist_rows.html", {
        "request": request,
        "whitelist": entries,
        "workflows": all_workflows,
    })


@router.post("/whitelist")
async def add_whitelist(
    request: Request,
    entry_type: str = Form(...),
    platform: str = Form(""),
    phone: str = Form(""),
    group_id: str = Form(""),
    display_name: str = Form(""),
    notes: str = Form(""),
):
    phone = phone.strip().lstrip("+")
    group_id = group_id.strip()
    if entry_type == "person" and not phone:
        return HTMLResponse("Phone is required for person entries", status_code=400)
    if entry_type == "group" and not group_id:
        return HTMLResponse("Group is required for group entries", status_code=400)
    if entry_type == "person_in_group" and (not phone or not group_id):
        return HTMLResponse("Phone and group are required", status_code=400)

    await db.add_whitelist_entry(
        entry_type=entry_type, platform=platform,
        phone=phone, group_id=group_id,
        display_name=display_name.strip(), notes=notes.strip(),
    )

    hx_target = request.headers.get("HX-Target", "")
    if hx_target == "wl-toast":
        label = display_name or phone or group_id
        return HTMLResponse(f'<div class="notice">{label} added to whitelist</div>')

    return await _enriched_whitelist(request)


@router.post("/messages/whitelist-quick")
async def quick_whitelist(request: Request):
    """Quick-add from the messages page to the whitelist."""
    form = await request.form()
    entry_type = form.get("entry_type", "person")
    phone = form.get("phone", "").strip()
    group_id = form.get("group_id", "").strip()
    platform = form.get("platform", "whatsapp")
    display_name = form.get("display_name", "")

    # Check if already whitelisted
    existing = await db.get_whitelist()
    for e in existing:
        et = e.get("entry_type", "")
        if et == "person" and entry_type == "person" and e.get("phone") == phone:
            return HTMLResponse(f'<span class="notice">{display_name or phone} already whitelisted</span>')
        if et == "group" and entry_type == "group" and e.get("group_id") == group_id:
            return HTMLResponse(f'<span class="notice">Group already whitelisted</span>')
        if et == "person_in_group" and entry_type == "person_in_group" and e.get("phone") == phone and e.get("group_id") == group_id:
            return HTMLResponse(f'<span class="notice">{display_name or phone} already whitelisted in this group</span>')

    await db.add_whitelist_entry(
        entry_type=entry_type,
        platform=platform,
        phone=phone,
        group_id=group_id,
        display_name=display_name,
        notes="Quick-added from messages",
    )
    label = display_name or phone or group_id
    return HTMLResponse(f'<span class="notice">✅ {label} whitelisted</span>')


@router.post("/messages/whitelist-remove")
async def quick_remove_whitelist(request: Request):
    """Quick-remove from the messages page whitelist."""
    form = await request.form()
    entry_id = int(form.get("entry_id", 0))
    if entry_id:
        await db.remove_whitelist_entry(entry_id)
    label = form.get("label", "Entry")
    return HTMLResponse(f'<span class="notice">❌ {label} removed from whitelist</span>')


@router.delete("/whitelist/{entry_id}")
async def delete_whitelist(request: Request, entry_id: int):
    await db.remove_whitelist_entry(entry_id)
    return await _enriched_whitelist(request)


@router.post("/whitelist/{entry_id}/toggle")
async def toggle_whitelist(request: Request, entry_id: int):
    entries = await db.get_whitelist()
    current = next((e for e in entries if e["id"] == entry_id), None)
    if current:
        await db.toggle_whitelist_entry(entry_id, not current["enabled"])
    return await _enriched_whitelist(request)


@router.post("/whitelist/{entry_id}/workflows")
async def update_whitelist_workflows(request: Request, entry_id: int):
    """Update workflow assignments for a whitelist entry."""
    form = await request.form()
    selected_ids = [int(v) for v in form.getlist("workflow_ids")]
    # Get current links
    current = await db.get_workflows_for_whitelist_entry(entry_id)
    current_ids = {w["id"] for w in current}
    # Add new links
    for wf_id in selected_ids:
        if wf_id not in current_ids:
            await db.link_whitelist_workflow(entry_id, wf_id)
    # Remove unlinked
    for wf_id in current_ids:
        if wf_id not in selected_ids:
            await db.unlink_whitelist_workflow(entry_id, wf_id)
    return await _enriched_whitelist(request)


# ---- Logs ----

@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    return templates.TemplateResponse("logs.html", {"request": request})


@router.get("/llm-logs", response_class=HTMLResponse)
async def llm_logs_page(request: Request):
    logs = await db.get_llm_logs(limit=200)
    llm_stats = await db.get_llm_stats()
    return templates.TemplateResponse("llm_logs.html", {
        "request": request,
        "logs": logs,
        "llm_stats": llm_stats,
    })


# ---- Database maintenance ----

@router.post("/config/clear/{target}")
async def clear_data(request: Request, target: str):
    valid = {"messages", "logs", "chats", "whitelist", "config", "llm_logs", "all"}
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


@router.post("/messages/{msg_id}/transcribe")
async def transcribe_message(msg_id: int):
    """Transcribe audio for a specific message and save result to DB."""
    from fastapi.responses import JSONResponse
    msg = await db.get_message(msg_id)
    if not msg:
        return JSONResponse({"error": "Message not found"}, status_code=404)
    if not msg.get("audio_path"):
        return JSONResponse({"error": "No audio for this message"}, status_code=400)

    audio_file = settings.data_dir / msg["audio_path"]
    if not audio_file.exists():
        return JSONResponse({"error": "Audio file missing"}, status_code=404)

    try:
        audio_bytes = audio_file.read_bytes()
        result = await transcriber_svc.transcribe(
            audio_bytes,
            filename=audio_file.name,
            language=None,
        )
        text = result.get("text", "").strip()
        if text:
            await db.update_message(msg_id, transcription=text)
        return JSONResponse({"text": text, "language": result.get("language", "")})
    except Exception as e:
        log.error("message_transcribe_failed", msg_id=msg_id, error=str(e))
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

    # Auto-whitelist the recipient so their replies are not blocked
    existing = await db.get_whitelist()
    is_group_chat = False
    if chat_rowid:
        chat_info = await db.get_chat(chat_rowid)
        is_group_chat = bool(chat_info and chat_info.get("is_group"))

    if is_group_chat:
        already = any(e.get("entry_type") == "group" and e.get("group_id") == chat_id for e in existing)
        if not already:
            await db.add_whitelist_entry(
                entry_type="group", group_id=chat_id,
                platform="whatsapp",
                display_name=chat_info.get("group_name", "") if chat_info else "",
                notes="Auto-whitelisted via web reply",
            )
            log.info("auto_whitelisted", chat_id=chat_id, entry_type="group", source="web_reply")
    else:
        already = any(e.get("entry_type") == "person" and e.get("phone") == chat_id for e in existing)
        if not already:
            await db.add_whitelist_entry(
                entry_type="person", phone=chat_id,
                platform="whatsapp",
                notes="Auto-whitelisted via web reply",
            )
            log.info("auto_whitelisted", chat_id=chat_id, entry_type="person", source="web_reply")

    # Add proper JID suffix for Evolution API
    if is_group_chat:
        if not chat_id.endswith("@g.us"):
            chat_id = f"{chat_id}@g.us"
    else:
        # DM contacts use LID format — append @lid so Evolution API doesn't
        # misinterpret them as phone numbers (@s.whatsapp.net)
        if not chat_id.endswith(("@lid", "@s.whatsapp.net")):
            chat_id = f"{chat_id}@lid"

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

# ---- Workflows ----

@router.get("/workflows", response_class=HTMLResponse)
async def workflows_page(request: Request):
    all_wf = await db.get_all_workflows()
    workflows = []
    for wf in all_wf:
        steps = await db.get_workflow_steps(wf["id"])
        linked = await db.get_whitelist_entries_for_workflow(wf["id"])
        wf["step_count"] = len(steps)
        wf["linked_contacts"] = len(linked)
        workflows.append(wf)
    return templates.TemplateResponse("workflows.html", {
        "request": request,
        "workflows": workflows,
    })


@router.post("/workflows")
async def create_workflow(request: Request, name: str = Form(...), description: str = Form("")):
    await db.create_workflow(name=name, description=description)
    return RedirectResponse("/workflows", status_code=303)


@router.post("/workflows/{workflow_id}/toggle-enabled")
async def toggle_workflow_enabled(request: Request, workflow_id: int):
    """Toggle workflow enabled state from list page."""
    wf = await db.get_workflow(workflow_id)
    if wf:
        new_val = 0 if wf.get("enabled") else 1
        await db.update_workflow(workflow_id, enabled=new_val)
        wf["enabled"] = new_val
    steps = await db.get_workflow_steps(workflow_id)
    linked = await db.get_whitelist_entries_for_workflow(workflow_id)
    wf["step_count"] = len(steps)
    wf["linked_contacts"] = len(linked)
    checked = "checked" if wf["enabled"] else ""
    label = "active" if wf["enabled"] else "off"
    return HTMLResponse(f"""<tr>
        <td><a href="/workflows/{wf['id']}"><strong>{wf['name']}</strong></a></td>
        <td style="font-size:0.82rem; color:var(--text-secondary);">{(wf['description'] or '')[:80]}</td>
        <td>{wf['step_count']}</td>
        <td>{wf['linked_contacts']}</td>
        <td>
            <label style="display:flex; align-items:center; gap:0.3rem; margin:0; cursor:pointer; font-size:0.8rem;">
                <input type="checkbox" {checked}
                       hx-post="/workflows/{wf['id']}/toggle-enabled"
                       hx-target="closest tr" hx-swap="outerHTML"
                       style="width:auto; margin:0;">
                {label}
            </label>
        </td>
        <td><a href="/workflows/{wf['id']}" class="outline" style="padding:2px 8px; font-size:0.75rem;">Edit</a></td>
    </tr>""")
    return RedirectResponse("/workflows", status_code=303)


@router.get("/workflows/{workflow_id}", response_class=HTMLResponse)
async def workflow_detail(request: Request, workflow_id: int):
    wf = await db.get_workflow_with_steps(workflow_id)
    if not wf:
        return HTMLResponse("Workflow not found", status_code=404)
    linked_whitelist = await db.get_whitelist_entries_for_workflow(workflow_id)
    all_whitelist = await db.get_whitelist()
    wf_logs = await db.get_workflow_logs(workflow_id=workflow_id, limit=50)
    return templates.TemplateResponse("workflow_detail.html", {
        "request": request,
        "workflow": wf,
        "linked_whitelist": linked_whitelist,
        "all_whitelist": all_whitelist,
        "wf_logs": wf_logs,
    })


@router.post("/workflows/{workflow_id}/update")
async def update_workflow(
    request: Request,
    workflow_id: int,
    name: str = Form(...),
    description: str = Form(""),
    enabled: int = Form(0),
):
    await db.update_workflow(workflow_id, name=name, description=description, enabled=enabled)
    if request.headers.get("HX-Request"):
        return HTMLResponse('<span class="notice">Saved</span>')
    return RedirectResponse(f"/workflows/{workflow_id}", status_code=303)


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(request: Request, workflow_id: int):
    await db.delete_workflow(workflow_id)
    if request.headers.get("HX-Request"):
        return HTMLResponse("", headers={"HX-Redirect": "/workflows"})
    return RedirectResponse("/workflows", status_code=303)


@router.post("/workflows/{workflow_id}/steps")
async def add_workflow_step(
    request: Request,
    workflow_id: int,
    step_type: str = Form(...),
    label: str = Form(""),
    config_json: str = Form("{}"),
    condition: str = Form(""),
):
    steps = await db.get_workflow_steps(workflow_id)
    next_order = max((s["step_order"] for s in steps), default=0) + 1
    await db.add_workflow_step(
        workflow_id, next_order, step_type,
        label=label, config_json=config_json, condition=condition,
    )
    return RedirectResponse(f"/workflows/{workflow_id}", status_code=303)


@router.post("/workflows/{workflow_id}/steps/{step_id}")
async def update_workflow_step(
    request: Request,
    workflow_id: int,
    step_id: int,
    label: str = Form(""),
    config_json: str = Form("{}"),
    condition: str = Form(""),
    enabled: int = Form(0),
):
    await db.update_workflow_step(
        step_id, label=label, config_json=config_json,
        condition=condition, enabled=enabled,
    )
    if request.headers.get("HX-Request"):
        return HTMLResponse("", headers={"HX-Redirect": f"/workflows/{workflow_id}"})
    return RedirectResponse(f"/workflows/{workflow_id}", status_code=303)


@router.delete("/workflows/{workflow_id}/steps/{step_id}")
async def delete_workflow_step(request: Request, workflow_id: int, step_id: int):
    await db.delete_workflow_step(step_id)
    if request.headers.get("HX-Request"):
        return HTMLResponse("", headers={"HX-Redirect": f"/workflows/{workflow_id}"})
    return RedirectResponse(f"/workflows/{workflow_id}", status_code=303)


@router.post("/workflows/{workflow_id}/link-whitelist")
async def link_whitelist(
    request: Request,
    workflow_id: int,
    whitelist_id: int = Form(...),
):
    await db.link_whitelist_workflow(whitelist_id, workflow_id)
    return RedirectResponse(f"/workflows/{workflow_id}", status_code=303)


@router.post("/workflows/{workflow_id}/unlink-whitelist/{whitelist_id}")
async def unlink_whitelist(request: Request, workflow_id: int, whitelist_id: int):
    await db.unlink_whitelist_workflow(whitelist_id, workflow_id)
    return RedirectResponse(f"/workflows/{workflow_id}", status_code=303)


# ---- WebSocket routes ----

@router.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await ws_logs(websocket)


@router.websocket("/ws/qr")
async def websocket_qr(websocket: WebSocket):
    await ws_qr(websocket)
