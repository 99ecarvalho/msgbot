# Webhook Payloads

Evolution API sends POST requests to the configured webhook URL for subscribed events.

## Endpoint

```
POST /webhook/whatsapp
```

Configured via `instance/create` or `webhook/set`. The bot receives webhooks at `http://bot:8000/webhook/whatsapp` (internal Docker network).

---

## Event: `messages.upsert`

Fired for every new message (incoming and outgoing).

### Text Message

```json
{
  "event": "messages.upsert",
  "instance": {
    "instanceName": "msgbot",
    "instanceId": "57888c15-...",
    "wuid": "10000000000003@lid"
  },
  "data": {
    "key": {
      "remoteJid": "10000000000001@lid",
      "fromMe": false,
      "id": "3EB0ABCDEF123456"
    },
    "pushName": "Alice",
    "message": {
      "conversation": "Hello bot!"
    },
    "messageType": "conversation",
    "messageTimestamp": 1778972000,
    "source": "android"
  }
}
```

### Group Text Message

```json
{
  "event": "messages.upsert",
  "data": {
    "key": {
      "remoteJid": "120363000000000001@g.us",
      "fromMe": false,
      "id": "3EB0ABCDEF123456",
      "participant": "10000000000002@lid"
    },
    "pushName": "Bob",
    "groupName": "BOT",
    "message": {
      "conversation": "Hello group!"
    },
    "messageType": "conversation",
    "source": "android"
  }
}
```

Key differences for groups:
- `remoteJid` ends with `@g.us`
- `participant` field identifies the actual sender (LID or phone JID)
- `groupName` / `groupSubject` contain the group name

### Audio/Voice Message

```json
{
  "event": "messages.upsert",
  "data": {
    "key": {
      "remoteJid": "10000000000001@lid",
      "fromMe": false,
      "id": "3EB0ABCDEF789012"
    },
    "pushName": "Alice",
    "message": {
      "audioMessage": {
        "url": "https://mmg.whatsapp.net/...",
        "mimetype": "audio/ogg; codecs=opus",
        "fileSha256": "...",
        "fileLength": "12345",
        "seconds": 5,
        "ptt": true,
        "mediaKey": "..."
      }
    },
    "messageType": "audioMessage",
    "source": "android"
  }
}
```

- `ptt: true` = voice note (push-to-talk); `ptt: false` = audio file
- `messageType` is `audioMessage` or `pttMessage`
- Media is not inline — use `getBase64FromMediaMessage` to download it

### Extended Text Message

Messages with links, mentions, or replies:

```json
{
  "message": {
    "extendedTextMessage": {
      "text": "Check this out https://example.com",
      "contextInfo": {
        "quotedMessage": { "conversation": "original message" },
        "isForwarded": false
      }
    }
  },
  "messageType": "extendedTextMessage"
}
```

### Protocol / System Messages

Skipped by the bot — no content to process:

```json
{
  "messageType": "protocolMessage"
}
```

```json
{
  "messageType": "reactionMessage"
}
```

---

## Event: `connection.update`

Fired when the WhatsApp connection state changes.

```json
{
  "event": "connection.update",
  "data": {
    "state": "open"
  }
}
```

States: `open`, `close`, `connecting`.

---

## Key Fields Reference

| Field | Location | Description |
|-------|----------|-------------|
| `key.remoteJid` | `data.key` | Chat identifier (DM JID or group JID) |
| `key.fromMe` | `data.key` | `true` if sent by the bot |
| `key.id` | `data.key` | Unique message ID |
| `key.participant` | `data.key` | Sender JID in group messages |
| `pushName` | `data` | Contact display name |
| `source` | `data` | Device type: `android`, `ios`, `web`, `desktop` |
| `messageType` | `data` | Message type discriminator |
| `messageTimestamp` | `data` | Unix timestamp |
| `groupName` | `data` | Group name (group messages only) |
| `instance.wuid` | `data.instance` | Bot's own WhatsApp JID |

## Bot Processing Flow

1. Receive webhook POST at `/webhook/whatsapp`
2. Filter: skip `fromMe`, `protocolMessage`, `reactionMessage`
3. Extract `chat_id` from `remoteJid` (strip `@` suffix)
4. Check whitelist
5. For audio: download via `getBase64FromMediaMessage`, transcribe, process
6. For text: extract from `conversation` or `extendedTextMessage.text`
7. Route through workflow engine
