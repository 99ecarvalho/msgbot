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
