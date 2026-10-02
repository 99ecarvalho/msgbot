# Evolution API — Integration Reference

Evolution API v2.2.3 with **Baileys** (WhatsApp Web multi-device) provides the WhatsApp messaging backend for MsgBot.

## Architecture

```
User (WhatsApp) ←→ WhatsApp servers ←→ Evolution API (Baileys) ←→ MsgBot (webhooks + REST)
```

| Component       | Container              | Internal Port | External Port |
|-----------------|------------------------|---------------|---------------|
| Evolution API   | `msgbot-evolution-api-1` | 8080          | 8085          |
| PostgreSQL      | `msgbot-postgres-1`     | 5432          | —             |
| Bot             | `msgbot-bot-1`          | 8000          | 8088          |

## Authentication

All requests require the `apikey` header:

```
apikey: <EVOLUTION_API_KEY>
```

The key is set via `AUTHENTICATION_API_KEY` env var in docker-compose and stored in the bot's `.env` as `EVOLUTION_API_KEY`.

## LID patches

The image built from `docker/evolution/` is the official
`atendai/evolution-api:v2.2.3`, with three fixes for WhatsApp LIDs applied to
its compiled code by `docker/evolution/apply-patches.js`. Their source
commits are in forks, pinned as git submodules:

| Submodule | Branch | Commit | Fix |
|-----------|--------|--------|-----|
| `external/evolution-api` | `fix/lid-validation-bypass` | [145209b](https://github.com/145209b/commit/145209b2c2551546d2666465d011c4dc2848226c) | Let `@lid` contacts bypass the `onWhatsApp` check (patch 1) |
| `external/baileys` | `fix/lid-jid-encoding` | [cfcc772](https://github.com/cfcc772/commit/cfcc7720091811e821c2196564d86a4971f54f4f) | Keep each participant's JID server when encrypting group messages (patches 2 and 3) |

Nothing is built from these submodules, so they are not fetched by default.
To read or work on the source:

```bash
git submodule update --init --checkout external/baileys external/evolution-api
```

When updating Evolution API or Baileys, check that each search string in
`apply-patches.js` still matches; the build fails if one doesn't.

## Documentation Index

| File | Description |
|------|-------------|
| [instance.md](instance.md) | Instance lifecycle — create, connect, QR, logout |
| [messaging.md](messaging.md) | Sending messages — text, audio, media |
| [webhooks.md](webhooks.md) | Incoming webhooks — events, payload structure |
| [jid-format.md](jid-format.md) | JID types — phone, LID, group, broadcast |
| [troubleshooting.md](troubleshooting.md) | Known issues and workarounds |

## Quick Reference

```bash
# Base URL (from host)
BASE=http://localhost:8085
KEY="your-api-key"

# Check connection
curl -s "$BASE/instance/connectionState/msgbot" -H "apikey: $KEY"

# Send text
curl -s -X POST "$BASE/message/sendText/msgbot" \
  -H "apikey: $KEY" -H "Content-Type: application/json" \
  -d '{"number": "10000000000001@lid", "text": "Hello"}'
```
