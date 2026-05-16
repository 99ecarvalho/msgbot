"""Azure OpenAI LLM client."""
from __future__ import annotations

import structlog
from openai import AsyncAzureOpenAI

from bot.config import settings

log = structlog.get_logger("services.llm")

_client: AsyncAzureOpenAI | None = None


def _get_client() -> AsyncAzureOpenAI:
    global _client
    if _client is None:
        _client = AsyncAzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
        )
    return _client


async def process_voice_message(transcription: str, system_prompt: str) -> str:
    """Process a transcribed voice message through the LLM."""
    client = _get_client()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": transcription},
    ]
    resp = await client.chat.completions.create(
        model=settings.azure_openai_deployment_name,
        messages=messages,
    )
    result = resp.choices[0].message.content or ""
    log.info(
        "llm_response",
        input_len=len(transcription),
        output_len=len(result),
        model=settings.azure_openai_deployment_name,
    )
    return result


async def process_forwarded_audio(transcription: str, user_instruction: str) -> str:
    """Process a forwarded audio transcription with a user-provided instruction."""
    client = _get_client()

    system = (
        "You receive transcriptions of audio messages that were forwarded to you. "
        "Follow the user's instruction about what to do with the transcription."
    )
    user_content = (
        f"## Instruction\n{user_instruction}\n\n"
        f"## Audio Transcription\n{transcription}"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]
    resp = await client.chat.completions.create(
        model=settings.azure_openai_deployment_name,
        messages=messages,
    )
    result = resp.choices[0].message.content or ""
    log.info(
        "llm_forwarded_response",
        transcription_len=len(transcription),
        instruction_len=len(user_instruction),
        output_len=len(result),
    )
    return result
