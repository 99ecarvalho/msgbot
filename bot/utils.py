# Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>
#
# This file is part of MsgBot. It is free software, licensed under the GNU
# Lesser General Public License v3.0 or later. See COPYING.LESSER and
# COPYING for details.
#
# SPDX-License-Identifier: LGPL-3.0-or-later

"""Shared audio utilities — download, convert, save."""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import structlog

from bot.config import settings

log = structlog.get_logger("utils")


def _audios_dir(chat_id: str) -> Path:
    d = settings.audios_dir / chat_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_audio_sync(chat_id: str, direction: str, audio_bytes: bytes, ext: str = "ogg") -> str:
    """Save audio to disk. Returns relative path from data dir."""
    ts = int(time.time() * 1000)
    rel = f"audios/{chat_id}/{ts}_{direction}.{ext}"
    full = settings.data_dir / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(audio_bytes)
    log.info("audio_saved", path=rel, size_bytes=len(audio_bytes))
    return rel


async def save_audio(chat_id: str, direction: str, audio_bytes: bytes, ext: str = "ogg") -> str:
    """Async wrapper for save_audio_sync."""
    return await asyncio.get_event_loop().run_in_executor(None, save_audio_sync, chat_id, direction, audio_bytes, ext)


async def convert_wav_to_ogg_opus(wav_bytes: bytes) -> bytes:
    """Convert WAV bytes to OGG Opus (for Telegram voice notes) via ffmpeg."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-i", "pipe:0", "-c:a", "libopus", "-b:a", "48k",
        "-application", "voip", "-f", "ogg", "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(wav_bytes)
    if proc.returncode != 0:
        log.error("ffmpeg_conversion_failed", stderr=stderr.decode(errors="replace")[:500])
        raise RuntimeError(f"ffmpeg failed: {stderr.decode(errors='replace')[:200]}")
    log.info("wav_to_ogg_converted", input_bytes=len(wav_bytes), output_bytes=len(stdout))
    return stdout


async def convert_to_ogg_opus(audio_bytes: bytes) -> bytes:
    """Convert any audio format to OGG Opus via ffmpeg."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-i", "pipe:0", "-c:a", "libopus", "-b:a", "48k",
        "-application", "voip", "-f", "ogg", "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(audio_bytes)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {stderr.decode(errors='replace')[:200]}")
    return stdout
