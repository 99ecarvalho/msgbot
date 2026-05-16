"""HTTP client for the Whisper transcriber service."""
from __future__ import annotations

import structlog
import httpx

from bot.config import settings

log = structlog.get_logger("services.transcriber")


async def transcribe(audio_bytes: bytes, filename: str = "audio.ogg", language: str | None = None) -> dict:
    """Send audio to transcriber and return parsed result.

    Returns dict with keys: text, language, language_probability, audio_duration_sec, elapsed_ms, segments
    """
    url = f"{settings.transcriber_url}/transcribe"
    files = {"file": (filename, audio_bytes)}
    data: dict = {"vad_filter": "true", "beam_size": "5"}
    if language:
        data["language"] = language

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, files=files, data=data)
        resp.raise_for_status()

    result = resp.json()
    log.info(
        "transcription_complete",
        text_len=len(result.get("text", "")),
        language=result.get("language"),
        duration_sec=result.get("audio_duration_sec"),
        elapsed_ms=result.get("elapsed_ms"),
    )
    return result


async def health() -> dict:
    """Check transcriber health."""
    url = f"{settings.transcriber_url}/health"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
    except Exception:
        return {"status": "unreachable"}
