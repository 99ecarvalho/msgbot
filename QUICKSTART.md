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
- an Azure OpenAI resource;
- a **transcriber** and a **TTS** service. They are not part of this
  repository: `docker-compose.yml` builds them from
  `../company-manager/framework/transcriber` and `../company-manager/framework/tts`.
  Change those two `build.context` paths to your own services. The HTTP API
  they must provide is described in the README, under
  [Requirements](README.md#requirements).

WhatsApp works on your own computer. Telegram needs a server reachable from
the internet over HTTPS; see
[Deploying to a server](#deploying-to-a-server-telegram).

## 1. Get the code

```bash
git clone https://github.com/99ecarvalho/msgbot.git
cd msgbot
```

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

The first build, and the first transcription, download speech models and
can take several minutes. Follow the logs with `docker compose logs -f bot`, and stop
everything with `docker compose down` (your data stays in Docker volumes).

## 5. Pair WhatsApp

1. Open <http://localhost:8088>. The dashboard shows whether each service is
   healthy.
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

3. Put a reverse proxy with TLS in front of the bot. With
   [Caddy](https://caddyserver.com/), which gets a Let's Encrypt certificate
   by itself, this `Caddyfile` exposes only the webhooks and protects the web
   UI with a password (create the hash with `caddy hash-password`):

   ```caddyfile
   bot.example.com {
       @webhooks path /webhook/*
       handle @webhooks {
           reverse_proxy localhost:8088
       }
       handle {
           basic_auth {
               admin $2a$14$...your-bcrypt-hash...
           }
           reverse_proxy localhost:8088
       }
   }
   ```

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
./build.sh
./run.sh -d
```

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
| Transcriber fails to start | The NVIDIA Container Toolkit is installed and the GPU check above works |
| WhatsApp group or `@lid` contacts fail | See [doc/evolution/troubleshooting.md](doc/evolution/troubleshooting.md) |
