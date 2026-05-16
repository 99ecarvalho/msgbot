# Instance Management

## Create Instance

Creates a new WhatsApp instance or returns existing if the name is already in use.

```
POST /instance/create
```

**Request:**

```json
{
  "instanceName": "msgbot",
  "integration": "WHATSAPP-BAILEYS",
  "qrcode": true,
  "webhook": {
    "url": "http://bot:8000/webhook/whatsapp",
    "byEvents": false,
    "base64": true,
    "events": ["MESSAGES_UPSERT", "CONNECTION_UPDATE"]
  }
}
```

**Response (201):** Instance details including hash/token.

**Response (403/409):** Instance already exists — safe to ignore.

**Bot code:** `evolution.create_instance()` — called at startup.

---

## Connection State

```
GET /instance/connectionState/{instanceName}
```

**Response:**

```json
{
  "instance": { "instanceName": "msgbot", "state": "open" }
}
```

States: `open` (connected), `close` (disconnected), `connecting` (pairing).

**Bot code:** `evolution.get_connection_status()`

---

## Connect / QR Code

Returns the QR code for WhatsApp pairing.

```
GET /instance/connect/{instanceName}
```

**Response:**

```json
{
  "pairingCode": null,
  "code": "2@...",
  "count": 0,
  "base64": "data:image/png;base64,..."
}
```

The `base64` field contains the QR image. If already connected, returns the connection state instead.

**Bot code:** `evolution.get_qr_code()`

---

## Logout / Disconnect

Logs out the WhatsApp session. **WARNING:** This wipes all Baileys Signal protocol sessions — group messaging will break until sessions are re-established.

```
DELETE /instance/logout/{instanceName}
```

**Bot code:** `evolution.disconnect_instance()`

> **Never call this in production unless you intend a full re-pair.** After logout, you must scan QR again and all per-participant encryption sessions are lost.

---

## Set Webhook

Configures/updates the webhook URL for an existing instance.

```
POST /webhook/set/{instanceName}
```

**Request:**

```json
{
  "webhook": {
    "url": "http://bot:8000/webhook/whatsapp",
    "enabled": true,
    "webhookByEvents": false,
    "webhookBase64": true,
    "events": ["MESSAGES_UPSERT", "CONNECTION_UPDATE"]
  }
}
```

**Bot code:** `evolution.set_webhook()`

### Webhook Events

| Event | Description |
|-------|-------------|
| `MESSAGES_UPSERT` | New incoming/outgoing message |
| `CONNECTION_UPDATE` | Connection state change (open/close) |
