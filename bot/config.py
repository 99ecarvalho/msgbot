# Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>
#
# This file is part of MsgBot. It is free software, licensed under the GNU
# Lesser General Public License v3.0 or later. See COPYING.LESSER and
# COPYING for details.
#
# SPDX-License-Identifier: LGPL-3.0-or-later

"""Application configuration via environment variables."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- LLM provider: "azure_openai" or "azure_anthropic" ---
    llm_provider: str = "azure_openai"

    # --- Azure OpenAI ---
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment_name: str = "gpt-4.1"
    azure_openai_api_version: str = "2024-12-01-preview"

    # --- Azure-hosted Anthropic ---
    anthropic_model: str = "claude-opus-4-6"

    # --- Messaging API Keys ---
    telegram_bot_token: str = ""
    evolution_api_key: str = ""

    # --- Service URLs ---
    evolution_api_url: str = "http://evolution-api:8080"
    evolution_instance_name: str = "msgbot"
    transcriber_url: str = "http://transcriber:8000"
    tts_url: str = "http://tts:8000"

    # --- Bot ---
    bot_url: str = "http://localhost:8000"
    default_system_prompt: str = "You are a helpful voice assistant. Respond concisely and naturally."
    response_mode: str = "auto"  # text | voice | auto

    # --- Web UI login ---
    web_username: str = "admin"
    web_password: str = ""  # empty: a random password is generated and logged at startup

    # --- Data ---
    data_dir: Path = Path("/app/data")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "msgbot.db"

    @property
    def audios_dir(self) -> Path:
        return self.data_dir / "audios"

    # .env is shared with docker compose, which reads settings for the other
    # services (e.g. WHISPER_MODEL) from it; ignore keys that aren't ours.
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
