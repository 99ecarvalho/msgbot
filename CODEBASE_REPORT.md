# MsgBot — Codebase Report

Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>

A technical walkthrough of the code: how it is organized, how a message
flows through it, and where its strengths and gaps are. For setup and usage,
see [README.md](README.md) and [QUICKSTART.md](QUICKSTART.md).

- [1. Overview](#1-overview)
- [2. Project statistics](#2-project-statistics)
- [3. Architecture](#3-architecture)
- [4. Directory structure](#4-directory-structure)
- [5. Modules](#5-modules)
- [6. Message flow](#6-message-flow)
- [7. Dependencies](#7-dependencies)
- [8. Security](#8-security)
- [9. Database](#9-database)
- [10. Docker infrastructure](#10-docker-infrastructure)
- [11. Code distribution](#11-code-distribution)
- [12. Quality summary](#12-quality-summary)

---

## 1. Overview

**MsgBot** is a multi-platform voice bot (WhatsApp and Telegram) built with
**FastAPI**. It receives voice or text messages, transcribes audio with
Whisper, processes the text with an LLM (Azure OpenAI, or Anthropic models
hosted on Azure), and replies with text or voice (Piper TTS). It includes a
complete web UI with a dashboard, message history, configurable workflows,
and a whitelist.

---

## 2. Project statistics

Line counts include the license header at the top of each file.

| Metric | Value |
| --- | --- |
| **Main language** | Python 3.11 |
| **Web framework** | FastAPI + Uvicorn |
| **Python modules** | 13 (+ 4 `__init__.py`) |
| **Python lines** | **3,657** |
| **HTML templates (Jinja2)** | 13 files / **2,357 lines** |
| **Custom CSS** | 901 lines |
| **JavaScript** | 22 lines in `app.js`, inline scripts in templates (+ vendored htmx / Pico CSS) |
| **Evolution API patch script** | 104 lines (Node.js) |
| **Total** | ~7,000 lines |
| **Python dependencies** | 12 packages |
| **Docker containers** | 5 (bot, evolution-api, transcriber, tts, postgres) |
| **Automated tests** | None |
| **License** | LGPL-3.0-or-later |

---

## 3. Architecture

```text
               webhook                    webhook
Evolution API ──────────► FastAPI Bot ◄──────── Telegram Bot API
 (WhatsApp)               :8000                 (python-telegram-bot)
                          │       │
                  Web UI ◄┘       └► SQLite + audio files
              (Jinja2 + HTMX)
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
     Transcriber         LLM             TTS
  (faster-whisper)  (Azure OpenAI /    (Piper)
                     Anthropic)
```

### Service ports

| Service | Host port | Internal port | Description |
| --- | --- | --- | --- |
| Bot (web UI + webhooks) | `8088` | `8000` | FastAPI: dashboard, QR, messages, config, logs |
| Evolution API | `8085` | `8080` | WhatsApp bridge (Baileys), REST API, patched for LID support |
| Transcriber | `8001` | `8000` | faster-whisper, GPU speech-to-text (external) |
| TTS | `8002` | `8000` | Piper TTS, PT-BR voice by default (external) |
| PostgreSQL | — | `5432` | Evolution API database (internal only) |

The transcriber and TTS services are not part of this repository; see
[Requirements](README.md#requirements) for the HTTP contract they meet.

---

## 4. Directory structure

```text
bot/
├── main.py           (153 LOC)  FastAPI app, lifecycle, webhook endpoints
├── config.py          (59 LOC)  Settings from env vars (pydantic-settings)
├── db.py             (904 LOC)  SQLite data layer (aiosqlite)
├── engine.py         (480 LOC)  Workflow engine: the step pipeline
├── utils.py           (75 LOC)  Audio utilities (save, ffmpeg conversion)
├── handlers/
│   ├── telegram.py   (205 LOC)  Telegram handler (commands + messages)
│   └── whatsapp.py   (280 LOC)  WhatsApp handler (Evolution API webhooks)
├── services/
│   ├── evolution.py  (193 LOC)  Evolution API HTTP client
│   ├── llm.py        (163 LOC)  LLM client (Azure OpenAI / Anthropic)
│   ├── transcriber.py (55 LOC)  Whisper HTTP client
│   └── tts.py         (44 LOC)  Piper TTS HTTP client
├── web/
│   ├── routes.py     (889 LOC)  Web UI routes (dashboard, config, etc.)
│   └── ws.py         (129 LOC)  WebSockets for live logs and QR code
├── templates/       (2,357 LOC) 13 Jinja2 templates
└── static/                      CSS, JS, htmx, Pico CSS
docker/evolution/                Evolution API image + LID patches
doc/evolution/                   Evolution API reference notes
```

---

## 5. Modules

### 5.1 `main.py` — Application entry point

- **Lifecycle (lifespan):** initializes the database, creates the Evolution
  API instance, and registers the Telegram and WhatsApp webhooks.
- **Endpoints:** `POST /webhook/telegram`, `POST /webhook/whatsapp`,
  `GET /health`.
- **Logging:** structlog with JSON output and ISO timestamps.
- **Background tasks:** WhatsApp webhooks are processed in the background
  with `asyncio.create_task`; the tasks are kept in a set so they aren't
  garbage-collected, and their exceptions are logged. Telegram updates are
  processed inline.

### 5.2 `config.py` — Configuration

- Uses `pydantic-settings` `BaseSettings` to load environment variables.
- Reads a `.env` file.
- Derived properties: `db_path`, `audios_dir`.
- Settings: LLM provider (`azure_openai` or `azure_anthropic`), Azure OpenAI
  endpoint/key/deployment, Anthropic model, Telegram token, Evolution API
  key/URL/instance, transcriber/TTS URLs, bot URL, default system prompt,
  response mode, and data directory.

### 5.3 `db.py` — Data layer (904 LOC, the largest file)

**Database:** SQLite through `aiosqlite`, with WAL mode and foreign keys.

**Tables (10):**

| Table | Purpose |
| --- | --- |
| `chats` | Conversations (platform, chat_id, display name, group, prompt, response mode) |
| `messages` | Messages (direction, type, text, audio, transcription, LLM reply, sender, device, blocked flag) |
| `config` | Global key-value configuration |
| `logs` | System logs |
| `whitelist` | Whitelist with three entry types: person, group, person_in_group |
| `workflows` | Configurable workflows |
| `workflow_steps` | Steps of each workflow (type, JSON config, condition) |
| `whitelist_workflows` | Many-to-many link between whitelist entries and workflows |
| `workflow_logs` | Per-step workflow execution logs |
| `llm_logs` | Detailed LLM call logs (prompt, reply, tokens, latency) |

**Features:**

- Full CRUD for every entity.
- Inline migrations (`ALTER TABLE` in `try/except`), including a migration
  of old whitelist entries to the three-type format.
- Seeds three example workflows (all disabled) on an empty database.
- Statistics (messages, chats, audio, LLM tokens).
- Whitelist matching by person, group, and person-in-group.

### 5.4 `engine.py` — Workflow engine (480 LOC, the core of the bot)

**Concept:** each message goes through a pipeline of configurable steps.

**Step types:**

| Step | Purpose |
| --- | --- |
| `transcribe` | Transcribes audio with Whisper |
| `llm` | Processes the text with the LLM |
| `reply_text` | Sends a text reply (optional template with `{text}` / `{transcription}`) |
| `reply_audio` | Synthesizes speech (TTS) and sends it as a voice note |
| `save` | Saves/updates the message in the database |

**Conditions:** `has_audio`, `has_text`, `mode_voice`, `mode_auto_voice`.

**Protections:**

- **Echo detection:** the bot remembers a SHA-256 hash of each text it sends
  for 30 seconds, and ignores an incoming message that matches, so it never
  answers itself.
- **Bounded cache:** the echo cache is an `OrderedDict` capped at 500
  entries.
- **Fault tolerance:** a failing step is logged with its error and the
  workflow continues.

**Abstractions:**

- `MessageSender` (Protocol): one interface for sending text and audio.
- `WhatsAppSender` / `TelegramSender`: the concrete implementations.
  WhatsApp replies use the full JID, so `@lid` contacts and groups work.
- `WorkflowContext` (dataclass): the state carried through the pipeline.

### 5.5 `handlers/whatsapp.py` — WhatsApp (280 LOC)

- Receives Evolution API webhooks (`messages.upsert`, `connection.update`).
- Skips the bot's own messages (`fromMe`), protocol and reaction messages,
  and status updates.
- Detects the sender's device (Android/iOS/Web) from Evolution API's
  `source` field, falling back to a heuristic on the message ID.
- Groups: extracts the `participant` and group name, fetching group
  metadata when needed.
- Downloads media through Evolution API (`getBase64FromMediaMessage`).
- Saves and auto-transcribes every audio message, even from chats that
  aren't whitelisted.
- Checks the whitelist; blocked messages are saved with `blocked=True`.
- Hands whitelisted messages to the engine (`process_message`).

### 5.6 `handlers/telegram.py` — Telegram (205 LOC)

- Uses `python-telegram-bot` in webhook mode.
- Commands: `/start`, `/help`, `/mode`, `/prompt`.
- Handlers for voice/audio and text, with the whitelist check.
- Downloads audio through the Telegram API.
- Auto-transcribes audio.
- Hands messages to the engine.

### 5.7 `services/` — External service clients

| Service | File | Client | Timeout |
| --- | --- | --- | --- |
| Evolution API | `evolution.py` | `httpx.AsyncClient` | 10–60 s |
| LLM | `llm.py` | `AsyncAzureOpenAI` / `AsyncAnthropic` | SDK default |
| Transcriber | `transcriber.py` | `httpx.AsyncClient` | 120 s |
| TTS | `tts.py` | `httpx.AsyncClient` | 60 s |

**LLM (`llm.py`):**

- Two providers, chosen with `LLM_PROVIDER`: Azure OpenAI, or Anthropic
  models served from the same Azure endpoint (`/anthropic`).
- Two modes: `process_voice_message` (direct) and `process_forwarded_audio`
  (forwarded audio, processed with the user's instruction).
- Detailed logging: tokens, latency, prompt, and reply saved to `llm_logs`.
- One lazily created client per provider.

**Evolution (`evolution.py`):**

- Instance creation, connection status, and disconnect.
- QR code for pairing.
- Webhook registration.
- Sending text and audio (base64).
- Media download and group metadata.
- Health check.

### 5.8 `web/` — Web interface

**Routes (`routes.py`, 889 LOC):**

| Route | Purpose |
| --- | --- |
| `GET /` | Dashboard: health checks, stats, recent messages |
| `GET /qr` | QR code page for WhatsApp pairing (reconnect / disconnect) |
| `GET /messages` | Message history with filters, quick whitelist buttons |
| `POST /messages/reply` | Send a reply from the web UI |
| `POST /messages/{id}/transcribe` | Transcribe a stored audio on demand |
| `GET /whitelist` | Whitelist management and workflow links |
| `GET /workflows`, `GET /workflows/{id}` | Workflow list and editor |
| `GET /config` | Global and per-chat configuration, database maintenance |
| `GET /stats` | Statistics |
| `GET /tools` | Test tools (Whisper, TTS) |
| `GET /logs` | Live logs (WebSocket) |
| `GET /llm-logs` | LLM call logs |
| `GET /audios/{path}` | Serves audio files |

**WebSockets (`ws.py`):**

- `/ws/logs`: streams logs to the web UI in real time, starting with the
  most recent 50.
- `/ws/qr`: QR code updates, polling the connection status.

**Frontend:**

- Jinja2 templates with Pico CSS (a classless CSS framework), dark theme.
- htmx for dynamic interactions (forms, toggles, filters).
- Brazilian phone number formatting (+55); WhatsApp LIDs shown as IDs.
- Path traversal protection on the audio endpoint.
- Sender-controlled data (names, IDs, transcriptions) is escaped on the
  server and inserted with `textContent` in scripts.

---

## 6. Message flow

```text
1. Webhook received (Telegram / WhatsApp)
   │
2. Handler extracts: phone, push_name, type, media, device, group
   │
3. get_or_create_chat() — find or create the chat in SQLite
   │
4. Auto-transcription (Whisper) — always runs for audio
   │
5. Whitelist check — not allowed: save as blocked and stop
   │
6. process_message() (engine.py)
   │
   ├─ Echo detection (sent-message cache)
   ├─ Save the message to the database
   ├─ Find the workflows linked to the whitelist entry
   │
7. execute_workflow() — for each enabled workflow:
   │
   ├─ Step: transcribe   (if there is audio)
   ├─ Step: llm          (process with the LLM)
   ├─ Step: reply_text   (send a text reply)
   ├─ Step: reply_audio  (TTS + send audio)  [conditional]
   └─ Step: save         (update the database with transcription / reply)
```

---

## 7. Dependencies

```text
fastapi==0.115.5           # Web framework
uvicorn[standard]==0.32.0  # ASGI server
httpx==0.28.1              # Async HTTP client
openai==1.82.0             # Azure OpenAI SDK
anthropic==0.102.0         # Anthropic SDK (Azure-hosted models)
python-telegram-bot==21.10 # Telegram Bot API
python-multipart==0.0.17   # File uploads
aiosqlite==0.20.0          # Async SQLite
jinja2==3.1.4              # Templates
structlog==24.4.0          # Structured logging
pydantic-settings==2.7.1   # Configuration
websockets==14.1           # WebSocket support
```

**System dependency:** `ffmpeg` (WAV → OGG Opus conversion).

**Vendored frontend:** htmx 2.0.4 (0BSD), Pico CSS 2.1.1 (MIT).

---

## 8. Security

See [SECURITY.md](SECURITY.md) for the deployment guide and how to report a
vulnerability.

### In place ✅

- **Whitelist:** authorization by person, group, and person-in-group.
- **API key:** Evolution API is protected by the `apikey` header.
- **Path traversal:** the `/audios/{path}` endpoint checks
  `resolve().relative_to()` against the data directory.
- **Echo protection:** the sent-message cache prevents reply loops.
- **Input validation:** TTS text is limited to 5,000 characters.
- **Output escaping:** sender-controlled data is escaped in templates,
  server-built HTML snippets, and scripts.
- **Parameterized SQL:** every value goes through `?` placeholders.
- **Secrets in env vars:** all credentials are loaded from `.env`, which is
  ignored by git.

### Points of attention ⚠️

- **No web UI authentication or CSRF protection:** the dashboard, config,
  and every web route are open. Anyone who reaches the port can read
  messages, change the configuration, send replies, and unlink WhatsApp.
- **Unverified webhooks:** `/webhook/whatsapp` doesn't check that requests
  come from Evolution API, and the Telegram webhook is registered without a
  `secret_token`.
- **Dynamic SQL in `update_*` functions:** the `SET` clause is built with an
  f-string. Column names come from the code, never from a request, so it is
  safe, but the pattern is fragile.
- **No rate limiting** on webhooks or the web UI.
- **No HTTPS:** the bot expects a reverse proxy to terminate TLS.
- **Prompt injection:** message text goes to the LLM as-is; the LLM has no
  tools, so the risk is limited to its replies.

---

## 9. Database

**Engine:** SQLite in WAL (write-ahead logging) mode, for concurrent reads.

**Schema:** 10 tables, with indexes on `messages(chat_rowid)`,
`messages(created_at)`, `logs(created_at)`, `workflow_logs(run_id)`,
`workflow_logs(message_id)`, and `llm_logs(created_at)`.

**Migrations:** inline, with `ALTER TABLE` in `try/except` so they can run
on every startup. This works for a solo project but won't scale to many
contributors changing the schema.

**Seed:** three example workflows (Default Text Bot, Default Mixed Bot,
Audio Summary Bot) are created, disabled, when the database is empty. The
Audio Summary Bot's prompt and labels are in Brazilian Portuguese.

---

## 10. Docker infrastructure

```text
docker-compose.yml — 5 services
├── postgres:16-alpine   Evolution API database
├── evolution-api        Custom build (./docker/evolution): v2.2.3 + LID patches
├── transcriber          External build (faster-whisper on GPU)
├── tts                  External build (Piper TTS)
└── bot                  Local build (python:3.11-slim + ffmpeg)
```

**Volumes:** `postgres_data`, `evolution_data`, `whisper_cache`, `bot_data`.
**Network:** `msgbot-net` (bridge).
**GPU:** the transcriber reserves one NVIDIA GPU.

**Evolution API patches:** `docker/evolution/apply-patches.js` fixes
Baileys 6.7.12's handling of WhatsApp LIDs (Linked Identities) at image
build time, so direct messages to `@lid` contacts and group messages work.

---

## 11. Code distribution

```text
db.py             █████████████████████████ 904  (25%)
web/routes.py     ████████████████████████  889  (24%)
engine.py         █████████████             480  (13%)
handlers/wa.py    ████████                  280   (8%)
handlers/tg.py    ██████                    205   (6%)
services/evo.py   █████                     193   (5%)
services/llm.py   ████                      163   (4%)
main.py           ████                      153   (4%)
web/ws.py         ███                       129   (4%)
utils.py          ██                         75   (2%)
config.py         ██                         59   (2%)
services/trans.py █                          55   (2%)
services/tts.py   █                          44   (1%)
__init__.py (4)   █                          28   (1%)
                                     Total: 3,657
```

---

## 12. Quality summary

| Aspect | Rating |
| --- | --- |
| **Organization** | ⭐⭐⭐⭐⭐ Clean, modular structure with a clear separation of concerns |
| **Readability** | ⭐⭐⭐⭐ Clear code with good structured logging |
| **Abstraction** | ⭐⭐⭐⭐ Good use of Protocol, dataclasses, and a strategy pattern in the engine |
| **Logging** | ⭐⭐⭐⭐⭐ Excellent: structlog JSON, logs in the database, WebSocket streaming |
| **Error handling** | ⭐⭐⭐⭐ Steps keep running when one fails; errors are logged |
| **Security** | ⭐⭐⭐ Solid whitelist and output escaping, but no web UI authentication and unverified webhooks |
| **Tests** | ⭐ No automated tests |
| **Documentation** | ⭐⭐⭐⭐⭐ README, quick start, contributing guide, security policy, Evolution API notes, and module docstrings |
| **Scalability** | ⭐⭐⭐ SQLite limits concurrency; fine for personal or small-team use |
| **Frontend** | ⭐⭐⭐⭐ htmx + Pico CSS: light, functional, no build step |
