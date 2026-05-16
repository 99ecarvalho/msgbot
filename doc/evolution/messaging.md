# Sending Messages

All send endpoints follow the pattern:

```
POST /message/{method}/{instanceName}
```

## Send Text

```
POST /message/sendText/{instanceName}
```

**Request:**

```json
{
  "number": "10000000000001@lid",
  "text": "Hello, world!"
}
```

**Response (201):**

```json
{
  "key": {
    "remoteJid": "10000000000001@lid",
    "fromMe": true,
    "id": "3EB069EBE6AED306AEF3F39274A2AA3404CB3EFF"
  },
  "status": "PENDING",
  "message": { "conversation": "Hello, world!" },
  "messageType": "conversation",
  "messageTimestamp": 1778972265
}
```

**Bot code:** `evolution.send_text(to, text)`

### Number Format

The `number` field must include the JID suffix:

| Type | Format | Example |
|------|--------|---------|
| DM (LID) | `{lid}@lid` | `10000000000001@lid` |
| DM (phone) | `{phone}@s.whatsapp.net` | `5511900000001@s.whatsapp.net` |
| Group | `{groupId}@g.us` | `120363000000000001@g.us` |

> **Important:** If you send a bare number without a suffix, Evolution API's `createJid` function will guess: digits ≥ 18 chars → `@g.us`, otherwise → `@s.whatsapp.net`. This misclassifies LID numbers (typically 14 digits). Always include the suffix explicitly.

---

## Send Audio (Voice Note)

Sends an OGG Opus audio file as a WhatsApp voice note (PTT).

```
POST /message/sendWhatsAppAudio/{instanceName}
```

**Request (base64):**

```json
{
  "number": "10000000000001@lid",
  "audio": "<raw-base64-string>"
}
```

**Request (URL):**

```json
{
  "number": "10000000000001@lid",
  "audio": "https://example.com/audio.ogg"
}
```

**Request (file upload):** Use `multipart/form-data` with a `file` field.

> **Gotcha:** The `audio` field must be **raw base64** or a URL. Do NOT use a data URI (`data:audio/ogg;base64,...`) — the `class-validator` `isBase64()` check rejects the `data:` prefix.

**Response:** Same structure as `sendText` but with `messageType: "audioMessage"`.

**Bot code:** `evolution.send_audio(to, audio_bytes)` — encodes to raw base64.

### Audio Format

WhatsApp voice notes require **OGG Opus** format. The bot converts TTS WAV output to OGG Opus using `ffmpeg` before sending.

---

## Send Media (Generic)

For images, video, documents, etc.

```
POST /message/sendMedia/{instanceName}
```

**Request:**

```json
{
  "number": "10000000000001@lid",
  "mediatype": "image",
  "media": "<base64-or-url>",
  "caption": "Optional caption",
  "fileName": "photo.jpg"
}
```

Media types: `image`, `video`, `audio`, `document`.

> For `document` with base64, `fileName` is **required**.

---

## Get Media from Message

Retrieve media (audio, image, etc.) from an existing message by its ID.

```
POST /chat/getBase64FromMediaMessage/{instanceName}
```

**Request:**

```json
{
  "message": {
    "key": { "id": "3EB069EBE6AED306AEF3F39274A2AA3404CB3EFF" }
  },
  "convertToMp4": false
}
```

**Response:**

```json
{
  "base64": "<base64-encoded-media>",
  "mimetype": "audio/ogg; codecs=opus",
  "fileName": "audio.ogg"
}
```

**Bot code:** `evolution.get_media_base64(message_id)` — used to download incoming voice messages for transcription.

---

## Send Presence

Simulate typing indicator or online/offline presence.

```
POST /chat/sendPresence/{instanceName}
```

**Request:**

```json
{
  "number": "10000000000001@lid",
  "presence": "composing",
  "delay": 1000
}
```

Presence values: `composing`, `recording`, `paused`, `available`, `unavailable`.
