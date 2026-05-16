# MsgBot — WhatsApp & Telegram Voice Bot

Voice-driven bot for WhatsApp and Telegram. Send voice messages or forward audios — the bot transcribes them (Whisper), processes with an LLM (Azure OpenAI), and replies with text or a TTS voice note (Piper).

Includes a web UI for QR code pairing, message history with audio playback, live logs, and configuration.

## Architecture

```
                  webhook              webhook
  Evolution API ──────────► Python Bot ◄──────── Telegram Bot API
   (WhatsApp)               (FastAPI)
                            │       │
                    Web UI ◄┘       └► SQLite + Audio files
                (Jinja2+HTMX)
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
       Transcriber      Azure OpenAI      TTS
    (Faster-Whisper)     (GPT-4.1)     (Piper)
```

## Services & Ports

| Service | Host Port | Internal Port | Description |
|---------|-----------|---------------|-------------|
| **Bot (Web UI + Webhooks)** | `8088` | `8000` | FastAPI app — dashboard, QR page, message history, config, logs |
| **Evolution API** | `8085` | `8080` | WhatsApp bridge (Baileys) — REST API for sending/receiving messages |
| **Transcriber** | `8001` | `8000` | Faster-Whisper — GPU-accelerated speech-to-text |
| **TTS** | `8002` | `8000` | Piper TTS — text-to-speech (PT-BR default voice) |
| **PostgreSQL** | — | `5432` | Database for Evolution API (internal only) |

## Prerequisites

### Create a Telegram Bot

1. Open Telegram and search for **@BotFather** (the official bot for creating bots).
2. Send `/newbot`.
3. Choose a **display name** for your bot (e.g. "My Voice Bot").
4. Choose a **username** — must end in `bot` (e.g. `my_voice_bot` or `MyVoiceBot`).
5. BotFather replies with your **bot token** — a string like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`. Copy it.
6. (Optional) Customize your bot with BotFather commands:
   - `/setdescription` — short description shown when users first open the bot
   - `/setabouttext` — text shown in the bot's profile
   - `/setuserpic` — upload a profile picture

> **Keep the token secret.** Anyone with it can control your bot.

### Azure OpenAI

1. Create an Azure OpenAI resource at https://portal.azure.com.
2. Deploy a model (e.g. `gpt-4.1`) in Azure AI Studio.
3. Copy the **Endpoint**, **API Key**, and **Deployment Name** from the resource.

### Why You Need a Public URL (VPS)

Telegram sends messages to your bot via **webhooks** — Telegram's servers make HTTPS requests to a URL you provide. This means your bot **must be reachable from the internet**. Running on `localhost` alone will not work for Telegram.

**WhatsApp** (Evolution API) communicates with the bot over the internal Docker network, so it works on localhost. But if you also want Telegram, you need to deploy to a server with a public IP.

The recommended approach is to deploy to a VPS. If you only need WhatsApp, you can run everything locally.

## Quick Start — Local (WhatsApp only)

If you only need WhatsApp and don't need Telegram, you can run entirely on localhost.

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Azure OpenAI (required)
AZURE_OPENAI_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4.1

# Leave TELEGRAM_BOT_TOKEN empty to skip Telegram
TELEGRAM_BOT_TOKEN=

# Evolution API key — pick any strong password
# Generate with: openssl rand -hex 32
EVOLUTION_API_KEY=$(openssl rand -hex 32)

# For local-only, BOT_URL points to the bot inside Docker network
BOT_URL=http://bot:8000
```

### 2. Build & Run

```bash
./build.sh        # docker compose build
./run.sh           # docker compose up
# or in detached mode:
./run.sh -d
```

### 3. Access

- **Web UI**: http://localhost:8088
- **WhatsApp QR**: http://localhost:8088/qr — scan to link your WhatsApp
- **Evolution API**: http://localhost:8085 (direct access if needed)

## Quick Start — VPS (Telegram + WhatsApp)

Deploy to a VPS so Telegram can reach your bot via webhooks.

### 1. Configure environment (locally)

```bash
cp .env.example .env
```

Edit `.env` with your real values:

```env
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4.1

# Telegram token from @BotFather (see Prerequisites above)
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz

# Evolution API key
EVOLUTION_API_KEY=$(openssl rand -hex 32)

# Public URL — your VPS IP or domain, port 8088
# If you have a domain pointed at your VPS:
BOT_URL=https://your-domain.com:8088
# If using just the IP (HTTP, no TLS — Telegram requires HTTPS, see note below):
# BOT_URL=https://your-vps-ip:8088
```

> **Telegram requires HTTPS** for webhooks. Options:
> - Put a reverse proxy (Caddy, nginx) in front with a real domain + automatic TLS
> - Use a self-signed certificate (Telegram supports this — see [Telegram webhook guide](https://core.telegram.org/bots/webhooks))
> - Use Caddy (simplest — automatic HTTPS with Let's Encrypt, zero config)

### 2. Deploy to VPS

```bash
# Sync project files to VPS
rsync -avz --exclude '.env' --exclude '__pycache__' --exclude '.git' \
  ./ your-server:~/msgbot/

# Copy your .env separately (so it doesn't get overwritten on redeploys)
scp .env your-server:~/msgbot/.env
```

### 3. Build & Run on VPS

```bash
ssh your-server
cd ~/msgbot
./build.sh
./run.sh -d
```

### 4. Access

- **Web UI**: http://your-vps-ip:8088
- **WhatsApp QR**: http://your-vps-ip:8088/qr
- **Logs**: http://your-vps-ip:8088/logs

### Redeploying after changes

```bash
# From your local machine:
rsync -avz --exclude '.env' --exclude '__pycache__' --exclude '.git' \
  ./ your-server:~/msgbot/

ssh your-server "cd ~/msgbot && docker compose build bot && docker compose up -d bot"
```

## Web UI Pages

| Page | URL | Description |
|------|-----|-------------|
| Dashboard | `/` | Service health status, message stats, recent messages |
| WhatsApp QR | `/qr` | QR code for pairing (auto-refreshes via WebSocket) |
| Messages | `/messages` | Message history with audio playback, filterable by platform/chat |
| Config | `/config` | System prompt, response mode, per-chat overrides |
| Logs | `/logs` | Live log stream (WebSocket), filterable by level |

## Bot Commands

Available in both Telegram and WhatsApp:

| Command | Description |
|---------|-------------|
| `/mode voice\|text\|auto` | Set response mode (auto = voice reply to voice, text to text) |
| `/prompt <text>` | Set custom system prompt for this chat |
| `/help` | Show available commands |

## Features

- **Voice messages**: Send a voice note → transcribed → LLM response → text + optional TTS reply
- **Forwarded audio**: Forward any audio → transcribed → analyzed with your configurable prompt
- **Text messages**: Regular text is also processed through the LLM
- **Per-chat config**: Each chat can have its own system prompt and response mode
- **Audio storage**: All received and generated audio files are saved and playable from the web UI

## Project Structure

```
bot/
├── main.py                 # FastAPI app — webhooks, lifecycle, static files
├── config.py               # Pydantic Settings (env-based)
├── db.py                   # SQLite (aiosqlite) — chats, messages, config, logs
├── utils.py                # Audio save, WAV→OGG Opus conversion (ffmpeg)
├── handlers/
│   ├── telegram.py         # Telegram voice/audio/text handling
│   └── whatsapp.py         # WhatsApp via Evolution API webhooks
├── services/
│   ├── transcriber.py      # Whisper HTTP client
│   ├── tts.py              # Piper TTS HTTP client
│   ├── llm.py              # Azure OpenAI client
│   └── evolution.py        # Evolution API client (instance, QR, messaging)
├── web/
│   ├── routes.py           # Web UI routes (dashboard, QR, messages, config, logs)
│   └── ws.py               # WebSocket endpoints (live logs, QR updates)
├── templates/              # Jinja2 + HTMX (Pico CSS dark theme)
└── static/                 # CSS + JS
```

## Requirements

- Docker with Compose v2
- NVIDIA GPU + nvidia-container-toolkit (for Whisper transcriber)
- Azure OpenAI API access (endpoint + key)
- **For Telegram**: a VPS or server with a public IP + HTTPS (Telegram webhooks require a reachable URL)
- **For WhatsApp only**: localhost is fine (Evolution API uses internal Docker networking)
