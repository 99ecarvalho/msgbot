# 🎙️ MsgBot

[![License: LGPL v3+](https://img.shields.io/badge/license-LGPL--3.0--or--later-blue.svg)](COPYING.LESSER)

A self-hosted voice bot for WhatsApp and Telegram. Send it a voice note, or
forward it any audio, and it transcribes the audio (Whisper), processes the
text with an LLM (Azure OpenAI, or Anthropic models hosted on Azure), and
replies with text, a spoken voice note (Piper TTS), or both. What happens to
each message is defined by **workflows** you build in the web UI, and only
the contacts and groups you allow get a response.

Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>

- [Features](#features)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Workflows](#workflows)
- [Access control](#access-control)
- [Web UI](#web-ui)
- [Bot commands](#bot-commands)
- [Security](#security)
- [Development](#development)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

## Features

- **WhatsApp and Telegram**: WhatsApp through a self-hosted
  [Evolution API](https://github.com/EvolutionAPI/evolution-api) (pair with a
  QR code in the web UI), Telegram through a bot token from @BotFather.
- **Voice in, voice out**: voice notes and forwarded audio are transcribed;
  replies can be text, a TTS voice note, or both.
- **Workflows**: ordered steps (transcribe, LLM, reply with text, reply with
  audio, save) with conditions, edited in the web UI and assigned to
  contacts or groups.
- **Access control**: a whitelist of people, groups, and people within a
  group. Everything is logged; only whitelisted chats trigger workflows.
- **Per-chat settings**: each chat can have its own system prompt and
  response mode.
- **Two LLM providers**: Azure OpenAI deployments (default) or Anthropic
  models served from Azure AI Foundry.
- **Web UI**: dashboard, QR pairing, message history with audio playback,
  statistics, live logs, LLM call logs with token usage, and tools to try
  transcription and TTS by hand.
- **Everything stored locally**: messages, audio, and logs live in SQLite
  and on a Docker volume.

## Architecture

```text
                  webhook               webhook
  Evolution API ───────────► MsgBot ◄─────────── Telegram Bot API
   (WhatsApp)              (FastAPI)
                            │     │
                 Web UI  ◄──┘     └──► SQLite + audio files
              (Jinja2 + HTMX)
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
       Transcriber         LLM             TTS
    (faster-whisper)  (Azure OpenAI /    (Piper)
                       Anthropic)
```

`docker compose` starts these services:

| Service | Host port | Internal port | Description |
| ------- | --------- | ------------- | ----------- |
| **bot** | `8088` | `8000` | This project: web UI and webhooks |
| **evolution-api** | `8085` | `8080` | WhatsApp bridge, Evolution API v2.2.3 with the patches in `docker/evolution/` |
| **postgres** | (none) | `5432` | Database for Evolution API (internal only) |
| **transcriber** | `8001` | `8000` | [ai-transcriber](https://github.com/99ecarvalho/ai-transcriber): faster-whisper speech-to-text on the GPU (git submodule) |
| **tts** | `8002` | `8000` | [ai-tts](https://github.com/99ecarvalho/ai-tts): Piper text-to-speech, Brazilian Portuguese voice by default (git submodule) |

## Requirements

- Docker with Compose v2.
- An NVIDIA GPU and the
  [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/)
  for the Whisper transcriber.
- An Azure OpenAI resource with a deployed model (endpoint, key, and
  deployment name).
- **For Telegram**: a server reachable from the internet over HTTPS,
  because Telegram delivers messages by webhook. WhatsApp alone works on
  localhost.

The transcriber and TTS services are separate projects,
[ai-transcriber](https://github.com/99ecarvalho/ai-transcriber) and
[ai-tts](https://github.com/99ecarvalho/ai-tts), included as git submodules
in `external/` and built by `docker-compose.yml`.
Clone with `--recurse-submodules`, or run `git submodule update --init`
(`./run.sh` does this for you).

To use other services instead, change their `build.context` (or replace
`build` with an `image`) in `docker-compose.yml`. They only need to provide:

| Service | Endpoint | Request | Response |
| ------- | -------- | ------- | -------- |
| Transcriber | `POST /transcribe` | multipart `file`, plus optional `language`, `vad_filter`, `beam_size` | JSON with `text`, `language`, `audio_duration_sec`, `elapsed_ms` |
| TTS | `POST /synthesize` | JSON `{"text": "...", "voice": "..."}` (`voice` optional) | WAV audio |
| Both | `GET /health` | | JSON with `status` |

## Getting started

```bash
git clone --recurse-submodules https://github.com/99ecarvalho/msgbot.git
cd msgbot
cp .env.example .env     # then fill in your Azure keys
./run.sh
```

`./run.sh` fetches the submodules, generates the secrets in `.env`, builds
and starts the stack, and prints the web UI's address with the username and
password. Open it, log in, go to **WhatsApp QR**, and scan the code with
WhatsApp (*Linked devices → Link a device*). Then whitelist yourself and
enable a workflow. `./run.sh help` lists the other commands (stop, logs,
update, and more).

[QUICKSTART.md](QUICKSTART.md) walks through each step, including creating a
Telegram bot and deploying to a server.

## Configuration

All settings are environment variables, read from `.env`
(see [.env.example](.env.example)):

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `AZURE_OPENAI_ENDPOINT` | | Azure resource endpoint, e.g. `https://your-resource.cognitiveservices.azure.com/` |
| `AZURE_OPENAI_API_KEY` | | Azure API key |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | `gpt-4.1` | Model deployment used for chat |
| `AZURE_OPENAI_API_VERSION` | `2024-12-01-preview` | Azure OpenAI API version |
| `LLM_PROVIDER` | `azure_openai` | `azure_openai`, or `azure_anthropic` for Anthropic models on the same Azure endpoint |
| `ANTHROPIC_MODEL` | `claude-opus-4-6` | Model name when `LLM_PROVIDER=azure_anthropic` |
| `TELEGRAM_BOT_TOKEN` | | Token from @BotFather; leave empty to disable Telegram |
| `EVOLUTION_API_KEY` | | A password you choose to protect Evolution API (`openssl rand -hex 32`) |
| `EVOLUTION_API_URL` | `http://evolution-api:8080` | Evolution API address |
| `EVOLUTION_INSTANCE_NAME` | `msgbot` | WhatsApp instance name in Evolution API |
| `TRANSCRIBER_URL` | `http://transcriber:8000` | Transcriber address |
| `TTS_URL` | `http://tts:8000` | TTS address |
| `BOT_URL` | `http://localhost:8000` | Where webhooks reach the bot: `http://bot:8000` for WhatsApp only, your public HTTPS URL for Telegram |
| `WEB_USERNAME` | `admin` | Web UI login name |
| `WEB_PASSWORD` | | Web UI password. `./run.sh` generates one if it is empty; without one, the bot logs a new random password at every start |
| `DEFAULT_SYSTEM_PROMPT` | `You are a helpful voice assistant. ...` | System prompt when a chat has none |
| `RESPONSE_MODE` | `auto` | `text`, `voice`, or `auto` (voice reply to voice, text reply to text) |
| `DATA_DIR` | `/app/data` | Where the SQLite database and audio files are stored |
| `WHISPER_MODEL` | `large-v3` | Whisper model for the transcriber, e.g. `small` or `medium` for less GPU memory |
| `WHISPER_DEVICE` | `cuda` | Transcriber device: `cuda`, `cpu`, or `auto` |
| `WHISPER_PRELOAD` | `1` | Load the Whisper model when the transcriber starts instead of on the first request |

The system prompt and response mode can also be changed in the web UI, for
all chats or per chat.

## Workflows

A workflow is an ordered list of steps that runs for each incoming message.
Each step can have a condition, and a step is skipped when its condition is
false.

| Step | What it does |
| ---- | ------------ |
| `transcribe` | Sends the audio to the transcriber; the transcript becomes the current text. Optional `language` |
| `llm` | Sends the current text to the LLM with the step's prompt; the reply becomes the current text |
| `reply_text` | Sends the current text. Optional `template` with `{text}` and `{transcription}` placeholders |
| `reply_audio` | Converts the current text to speech and sends it as a voice note |
| `save` | Stores the transcription and LLM replies with the message |

| Condition | True when |
| --------- | --------- |
| `has_audio` | The message contains audio |
| `has_text` | There is text to process |
| `mode_voice` | The chat's response mode is `voice` |
| `mode_auto_voice` | The response mode is `voice`, or `auto` and the message was a voice note |

Three example workflows are created on first start, all disabled: a
**Default Text Bot**, a **Default Mixed Bot** (transcribe, LLM, reply with
text and, for voice notes, audio), and an **Audio Summary Bot** that sends
back a transcript and a short summary (its prompt and labels are in
Brazilian Portuguese). Each run is logged step by step and shown on the
workflow's page.

## Access control

MsgBot logs every message it receives, but **runs workflows only for
whitelisted chats**. A whitelist entry is one of:

- a **person**, for direct messages;
- an **entire group**;
- a **person in a group**, so the bot answers only that member.

Each entry can be limited to one platform and is linked to the workflows
that should run for it. Manage entries on the **Whitelist** page, or with the
quick buttons on the **Messages** page.

## Web UI

| Page | URL | Description |
| ---- | --- | ----------- |
| Dashboard | `/` | Service health, message counts, recent messages |
| WhatsApp QR | `/qr` | Pair, reconnect, or disconnect WhatsApp |
| Messages | `/messages` | History per chat with audio playback, manual replies, and transcription |
| Whitelist | `/whitelist` | Access control entries and their workflows |
| Stats | `/stats` | Usage statistics per chat |
| Workflows | `/workflows` | Create, edit, and enable workflows |
| Tools | `/tools` | Try transcription and TTS by hand |
| Config | `/config` | Default prompt, response mode, per-chat overrides, database maintenance |
| Logs | `/logs` | Live log stream |
| LLM Logs | `/llm-logs` | Every LLM call with prompt, reply, token counts, and timing |

## Bot commands

Available in WhatsApp and Telegram:

| Command | Description |
| ------- | ----------- |
| `/mode voice\|text\|auto` | Set this chat's response mode |
| `/prompt <text>` | Set this chat's system prompt |
| `/help` | Show the commands |

## Security

The web UI asks for a login (`WEB_USERNAME` / `WEB_PASSWORD`) and rejects
requests from other sites. The Telegram and WhatsApp webhooks only accept
requests carrying a secret the bot registers with each service. The UI is
still plain HTTP, so anything beyond your own computer or network needs a
reverse proxy with TLS. Read [SECURITY.md](SECURITY.md) before deploying, and
to report a vulnerability.

## Development

The bot is a Python 3.11 FastAPI application. To work on it outside Docker:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest                        # run the tests
DATA_DIR=./data python -m bot.main      # http://localhost:8000
```

It still needs Evolution API, the transcriber, and the TTS service, so the
easiest setup is to run those with `docker compose up -d evolution-api
transcriber tts` and point the `*_URL` variables at their host ports.

```text
bot/
├── main.py             FastAPI app: webhooks, startup, static files
├── config.py           Settings from environment variables
├── db.py               SQLite schema, migrations, and queries
├── engine.py           Workflow engine: steps, conditions, execution
├── utils.py            Audio storage and WAV to OGG Opus conversion (ffmpeg)
├── handlers/           Incoming Telegram and WhatsApp messages
├── services/           Clients for Evolution API, the LLM, transcriber, and TTS
├── web/                Web UI routes and WebSocket endpoints
├── templates/          Jinja2 + HTMX pages
└── static/             CSS, JavaScript, vendored htmx and Pico CSS
docker/evolution/       Evolution API image with LID patches
doc/evolution/          Notes on the Evolution API
external/ai-transcriber Transcriber service (git submodule)
external/ai-tts         TTS service (git submodule)
external/baileys        Source of the Baileys LID fix (submodule, not fetched by default)
external/evolution-api  Source of the Evolution API LID fix (submodule, not fetched by default)
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for more.

## Documentation

| Document | Contents |
| -------- | -------- |
| [QUICKSTART.md](QUICKSTART.md) | Step-by-step setup, Telegram, and deployment |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |
| [SECURITY.md](SECURITY.md) | Deployment security and reporting vulnerabilities |
| [CODEBASE_REPORT.md](CODEBASE_REPORT.md) | Code walkthrough: modules, message flow, database, and quality review |
| [doc/evolution/](doc/evolution/README.md) | Evolution API: instances, JID formats, messaging, webhooks, troubleshooting |

## Contributing

Bug reports, documentation fixes, and code are welcome. Report bugs and
suggest features in the [issue tracker](https://github.com/99ecarvalho/msgbot/issues),
and please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## License

Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>

MsgBot is free software: you can redistribute it and/or modify it under the
terms of the **GNU Lesser General Public License, version 3 or (at your
option) any later version**. The license text is in
[COPYING.LESSER](COPYING.LESSER); it supplements the GNU General Public
License v3, included as [COPYING](COPYING).

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE.

### Third-party components

| Component | License | Use |
| --------- | ------- | --- |
| [htmx](https://htmx.org/) 2.0.4 | 0BSD | Vendored in `bot/static/htmx.min.js` |
| [Pico CSS](https://picocss.com/) 2.1.1 | MIT | Vendored in `bot/static/pico.min.css` |
| [Evolution API](https://github.com/EvolutionAPI/evolution-api) | Apache-2.0 with additional conditions (see its LICENSE) | Docker image, patched at build time by `docker/evolution/apply-patches.js` |
| [ai-transcriber](https://github.com/99ecarvalho/ai-transcriber), [ai-tts](https://github.com/99ecarvalho/ai-tts) | LGPL-3.0-or-later | Git submodules in `external/`, each with its own license and dependencies |
| [Baileys](https://github.com/WhiskeySockets/Baileys), [Evolution API](https://github.com/EvolutionAPI/evolution-api) forks | MIT; Apache-2.0 with additional conditions | Git submodules in `external/` with the source of the LID patches; not fetched or built by default |

Python dependencies are listed in [requirements.txt](requirements.txt) and
keep their own licenses.

MsgBot is not affiliated with WhatsApp, Meta, or Telegram. Using unofficial
WhatsApp clients such as Evolution API may break WhatsApp's terms of service;
you are responsible for how you use it.
