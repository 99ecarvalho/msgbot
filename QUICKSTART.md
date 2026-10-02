# 🚀 Quick Start Guide

Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>

- [Before you start](#before-you-start)
- [1. Get the code](#1-get-the-code)
- [2. Get your keys](#2-get-your-keys)
- [3. Configure](#3-configure)
- [4. Build and start](#4-build-and-start)
- [5. Pair WhatsApp](#5-pair-whatsapp)
- [6. Make the bot answer](#6-make-the-bot-answer)
- [Deploying to a server (Telegram)](#deploying-to-a-server-telegram)
- [Updating](#updating)
- [Troubleshooting](#troubleshooting)

## Before you start

You need:

- Docker with Compose v2 (`docker compose version`);
- an NVIDIA GPU with the NVIDIA Container Toolkit, for the transcriber
  (`docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`
  should list your GPU);
- an Azure OpenAI resource.

The transcriber
([ai-transcriber](https://github.com/99ecarvalho/ai-transcriber)) and the
TTS service ([ai-tts](https://github.com/99ecarvalho/ai-tts)) come with the
code as git submodules in `external/`, and are built with the rest of the
stack.

WhatsApp works on your own computer. Telegram needs a server reachable from
the internet over HTTPS; see
[Deploying to a server](#deploying-to-a-server-telegram).

## 1. Get the code

```bash
git clone --recurse-submodules https://github.com/99ecarvalho/msgbot.git
cd msgbot
```

If you already cloned without `--recurse-submodules`, the `external/`
folders are empty; fetch them with:

```bash
git submodule update --init
```

`./build.sh` also does this when they are missing.

## 2. Get your keys

### Azure OpenAI

1. Create an Azure OpenAI resource in the [Azure portal](https://portal.azure.com).
2. Deploy a model (for example `gpt-4.1`) in Azure AI Foundry.
3. Copy the resource's **endpoint**, an **API key**, and the **deployment
   name**.

To use an Anthropic model deployed on the same Azure resource instead, set
`LLM_PROVIDER=azure_anthropic` and `ANTHROPIC_MODEL` to the model's name.

### Telegram (optional)

1. In Telegram, open **@BotFather** and send `/newbot`.
2. Choose a display name, then a username ending in `bot`.
3. BotFather replies with a **token** like
   `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`.

Keep the token secret: anyone who has it controls your bot.

### Evolution API key

This is a password you invent to protect your own Evolution API. Generate
one:

```bash
openssl rand -hex 32
```

## 3. Configure

```bash
cp .env.example .env
```

Edit `.env`:

```env
AZURE_OPENAI_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4.1

# Paste the output of `openssl rand -hex 32`
EVOLUTION_API_KEY=3f1c...

# Leave empty for WhatsApp only
TELEGRAM_BOT_TOKEN=

# WhatsApp only: the bot's address inside the Docker network
BOT_URL=http://bot:8000
```

Every variable is described in the README, under
[Configuration](README.md#configuration). Never commit `.env`; it is ignored by
git.

## 4. Build and start

```bash
./build.sh        # docker compose build
./run.sh -d       # docker compose up -d
```

The first build downloads the CUDA base image and the Piper voice, and the
transcriber downloads its Whisper model (about 3 GB for the default
`large-v3`) the first time it starts, so the first run can take a while.
Follow the logs with `docker compose logs -f bot transcriber`, and stop
everything with `docker compose down` (your data stays in Docker volumes).

With less GPU memory, choose a smaller model in `.env`, for example
`WHISPER_MODEL=small`. Without a GPU, set `WHISPER_DEVICE=cpu` and a small
model, and remove the `deploy:` block from the `transcriber` service in
`docker-compose.yml`. Transcription is then much slower.

## 5. Pair WhatsApp

1. Open the address `./run.sh` printed, usually <http://localhost:8088>, and
   log in as `admin` with the `WEB_PASSWORD` that `./run.sh` saved in `.env`.
   The dashboard shows whether each service is healthy.
2. Go to **WhatsApp QR**.
3. On your phone, open WhatsApp → **Settings** → **Linked devices** →
   **Link a device**, and scan the code.

The bot now receives messages sent to that WhatsApp account. It logs them on
the **Messages** page, but doesn't answer anyone yet.

## 6. Make the bot answer

1. Open **Workflows** and enable one, for example **Default Mixed Bot**
   (transcribe voice notes, ask the LLM, reply with text, and with audio for
   voice notes). Open it to see and edit its steps and prompts.
2. Open **Whitelist** and add an entry: yourself as a **Person (DM)**, an
   **Entire Group**, or a **Person in Group**. Link the workflow to it.
   You can also whitelist a chat straight from the **Messages** page.
3. Send a voice note from that chat. The run appears on the **Logs** page
   and on the workflow's page, and the LLM call on **LLM Logs**.

Commands work in any chat with the bot:

```text
/mode voice     reply with voice notes
/mode text      reply with text
/mode auto      voice reply to voice, text reply to text
/prompt Answer like a pirate.
/help
```

## Deploying to a server (Telegram)

Telegram sends each message to your bot with an HTTPS request, so the bot
must have a public HTTPS address.

1. Copy the project to the server, and the `.env` file separately:

   ```bash
   rsync -avz --exclude .env --exclude .git --exclude .venv --exclude __pycache__ \
       ./ user@your-server:msgbot/
   scp .env user@your-server:msgbot/.env
   ```

2. In the server's `.env`, set your token and public URL:

   ```env
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   BOT_URL=https://bot.example.com
   ```

3. Put a reverse proxy with TLS in front of the bot, so the login and the
   webhooks are encrypted. With [Caddy](https://caddyserver.com/), which gets
   a Let's Encrypt certificate by itself, this `Caddyfile` is enough:

   ```caddyfile
   bot.example.com {
       reverse_proxy localhost:8088
   }
   ```

   The bot itself asks for the web UI login and checks the webhooks' secrets.
   Set a strong `WEB_PASSWORD` in `.env` before exposing it.

4. Build and start on the server:

   ```bash
   ssh user@your-server
   cd msgbot
   ./build.sh
   ./run.sh -d
   ```

   On startup the bot registers `BOT_URL/webhook/telegram` with Telegram.

5. Block direct access to ports 8088, 8085, 8001, and 8002 in the server's
   firewall, so the only way in is through the proxy. Note that Docker's
   published ports bypass `ufw`; bind them to `127.0.0.1` in
   `docker-compose.yml` (for example `"127.0.0.1:8088:8000"`) or use your
   cloud provider's firewall.

Read [SECURITY.md](SECURITY.md) before exposing the bot to the internet.

## Updating

```bash
git pull
git submodule update --init --recursive   # check out the transcriber/TTS versions this commit uses
./build.sh
./run.sh -d
```

To move the transcriber and TTS to their latest `main` instead, run
`git submodule update --remote`, test, and commit the new submodule versions.

If you installed MsgBot before the transcriber and TTS became submodules,
the transcriber now uses a new `transcriber_cache` volume (the image no
longer runs as root). Once it works, you can delete the old one with
`docker volume rm msgbot_whisper_cache`.

To rebuild only the bot after changing its code:

```bash
docker compose build bot && docker compose up -d bot
```

The database migrates itself on startup.

## Troubleshooting

| Symptom | What to check |
| ------- | ------------- |
| A service shows as unreachable on the dashboard | `docker compose ps` and `docker compose logs <service>` |
| The QR code doesn't appear | `docker compose logs evolution-api`; try **Reconnect** on the QR page |
| Messages appear on **Messages** but get no answer | The chat is whitelisted, the entry is enabled, and an enabled workflow is linked to it |
| Telegram receives nothing | `BOT_URL` is public HTTPS and reachable; check `https://api.telegram.org/bot<token>/getWebhookInfo` |
| Logs show `webhook_rejected` | The request didn't carry the webhook secret. Restart the bot so it registers the webhooks again; after changing `TELEGRAM_BOT_TOKEN` or `EVOLUTION_API_KEY`, a restart is required |
| Forgot the web UI password | It is `WEB_PASSWORD` in `.env`; if that is empty, look for `web_password_generated` in `docker compose logs bot` |
| Transcriber fails to start | The NVIDIA Container Toolkit is installed and the GPU check above works; `docker compose logs transcriber` |
| Build fails with a missing `external/...` path | Run `git submodule update --init` |
| WhatsApp group or `@lid` contacts fail | See [doc/evolution/troubleshooting.md](doc/evolution/troubleshooting.md) |
