# Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>
#
# This file is part of MsgBot. It is free software, licensed under the GNU
# Lesser General Public License v3.0 or later. See COPYING.LESSER and
# COPYING for details.
#
# SPDX-License-Identifier: LGPL-3.0-or-later

"""LLM client supporting Azure OpenAI and Azure-hosted Anthropic models."""
from __future__ import annotations

import time
from typing import Any

import structlog

from bot.config import settings
from bot import db

log = structlog.get_logger("services.llm")

_openai_client: Any = None
_anthropic_client: Any = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import AsyncAzureOpenAI
        _openai_client = AsyncAzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
        )
    return _openai_client


def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        from anthropic import AsyncAnthropic
        _anthropic_client = AsyncAnthropic(
            base_url=settings.azure_openai_endpoint.rstrip("/") + "/anthropic",
            api_key="unused",
            default_headers={
                "Authorization": f"Bearer {settings.azure_openai_api_key}",
            },
        )
    return _anthropic_client


async def _chat(
    system_prompt: str,
    user_message: str,
) -> tuple[str, int, int, int, int, str]:
    """Route to the configured provider and return (reply, prompt_tok, compl_tok, total_tok, elapsed_ms, model)."""
    t0 = time.monotonic()

    if settings.llm_provider == "azure_anthropic":
        client = _get_anthropic_client()
        resp = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        result = resp.content[0].text if resp.content else ""
        prompt_tokens = resp.usage.input_tokens
        completion_tokens = resp.usage.output_tokens
        total_tokens = prompt_tokens + completion_tokens
        model_name = settings.anthropic_model
    else:
        client = _get_openai_client()
        resp = await client.chat.completions.create(
            model=settings.azure_openai_deployment_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        result = resp.choices[0].message.content or ""
        usage = resp.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        total_tokens = usage.total_tokens if usage else 0
        model_name = settings.azure_openai_deployment_name

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return result, prompt_tokens, completion_tokens, total_tokens, elapsed_ms, model_name


async def process_voice_message(
    transcription: str,
    system_prompt: str,
    chat_id: str = "",
    sender_phone: str = "",
) -> str:
    """Process a transcribed voice message through the LLM."""
    result, prompt_tokens, completion_tokens, total_tokens, elapsed_ms, model_name = (
        await _chat(system_prompt, transcription)
    )
    log.info(
        "llm_response",
        input_len=len(transcription),
        output_len=len(result),
        model=model_name,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    await db.save_llm_log(
        model=model_name,
        system_prompt=system_prompt,
        user_message=transcription,
        assistant_reply=result,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        elapsed_ms=elapsed_ms,
        chat_id=chat_id,
        sender_phone=sender_phone,
    )
    return result


async def process_forwarded_audio(
    transcription: str,
    user_instruction: str,
    chat_id: str = "",
    sender_phone: str = "",
) -> str:
    """Process a forwarded audio transcription with a user-provided instruction."""
    system = (
        "You receive transcriptions of audio messages that were forwarded to you. "
        "Follow the user's instruction about what to do with the transcription."
    )
    user_content = (
        f"## Instruction\n{user_instruction}\n\n"
        f"## Audio Transcription\n{transcription}"
    )
    result, prompt_tokens, completion_tokens, total_tokens, elapsed_ms, model_name = (
        await _chat(system, user_content)
    )
    log.info(
        "llm_forwarded_response",
        transcription_len=len(transcription),
        instruction_len=len(user_instruction),
        output_len=len(result),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    await db.save_llm_log(
        model=model_name,
        system_prompt=system,
        user_message=user_content,
        assistant_reply=result,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        elapsed_ms=elapsed_ms,
        chat_id=chat_id,
        sender_phone=sender_phone,
    )
    return result
