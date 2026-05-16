"""WebSocket endpoints — live logs and QR code updates."""
from __future__ import annotations

import asyncio
import json
import time

import structlog
from fastapi import WebSocket, WebSocketDisconnect

from bot.services import evolution
from bot import db

log = structlog.get_logger("web.ws")

# Connected WebSocket clients for log streaming
_log_clients: list[WebSocket] = []


async def broadcast_log(level: str, message: str, source: str = "", extra: dict | None = None):
    """Broadcast a log entry to all connected WebSocket clients and save to DB."""
    await db.save_log(level, message, source, extra)
    payload = json.dumps({
        "level": level,
        "source": source,
        "message": message,
        "extra": extra or {},
        "timestamp": time.time(),
    })
    disconnected = []
    for ws in _log_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        _log_clients.remove(ws)


async def ws_logs(websocket: WebSocket):
    """WebSocket endpoint for live log streaming."""
    await websocket.accept()
    _log_clients.append(websocket)
    try:
        # Send recent logs on connect
        recent = await db.get_logs(limit=50)
        for entry in recent:
            await websocket.send_text(json.dumps({
                "level": entry["level"],
                "source": entry["source"],
                "message": entry["message"],
                "extra": json.loads(entry.get("extra_json", "{}")),
                "timestamp": entry["created_at"],
            }))
        # Keep connection alive
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in _log_clients:
            _log_clients.remove(websocket)


async def ws_qr(websocket: WebSocket):
    """WebSocket endpoint for QR code updates."""
    await websocket.accept()
    instance_ensured = False
    try:
        while True:
            # Ensure instance exists before trying to connect
            if not instance_ensured:
                try:
                    await evolution.create_instance()
                    instance_ensured = True
                except Exception as e:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "error": f"Could not create instance: {e}",
                    }))
                    await asyncio.sleep(5)
                    continue

            # Check connection status
            status = await evolution.get_connection_status()
            state = status.get("instance", {}).get("state", status.get("state", "unknown"))

            if state == "open":
                await websocket.send_text(json.dumps({
                    "type": "connected",
                    "state": state,
                    "data": status,
                }))
                # Still poll to detect disconnections
                await asyncio.sleep(10)
            else:
                # Fetch QR code
                qr_data = await evolution.get_qr_code()
                if "error" in qr_data:
                    # Instance may have been deleted, try recreating
                    if "404" in str(qr_data.get("error", "")) or "not exist" in str(qr_data.get("error", "")).lower():
                        instance_ensured = False
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "error": qr_data["error"],
                    }))
                else:
                    base64_qr = qr_data.get("base64", "")
                    code = qr_data.get("code", "")
                    await websocket.send_text(json.dumps({
                        "type": "qr",
                        "base64": base64_qr,
                        "code": code,
                        "state": state,
                    }))
                # QR codes refresh roughly every 20s
                await asyncio.sleep(15)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning("ws_qr_error", error=str(e))
