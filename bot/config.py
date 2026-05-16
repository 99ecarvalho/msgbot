"""Application configuration via environment variables."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Azure OpenAI ---
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment_name: str = "gpt-4.1"
    azure_openai_api_version: str = "2024-12-01-preview"

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

    # --- Data ---
    data_dir: Path = Path("/app/data")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "msgbot.db"

    @property
    def audios_dir(self) -> Path:
        return self.data_dir / "audios"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
