"""HTTP client for the Piper TTS service."""
from __future__ import annotations

import structlog
import httpx

from bot.config import settings

log = structlog.get_logger("services.tts")


async def synthesize(text: str, voice: str | None = None) -> bytes:
    """Convert text to WAV audio bytes."""
    url = f"{settings.tts_url}/synthesize"
    payload: dict = {"text": text}
    if voice:
        payload["voice"] = voice

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()

    log.info("tts_complete", text_len=len(text), audio_bytes=len(resp.content))
    return resp.content


async def health() -> dict:
    """Check TTS health."""
    url = f"{settings.tts_url}/health"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
    except Exception:
        return {"status": "unreachable"}
