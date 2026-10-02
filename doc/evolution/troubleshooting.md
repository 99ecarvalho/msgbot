# Troubleshooting

## Common Errors

### `Owned media must be a url, base64, or valid file with buffer`

**Endpoint:** `POST /message/sendWhatsAppAudio/{instance}`

**Cause:** The `audio` field contains a data URI (`data:audio/ogg;base64,...`) instead of raw base64. Evolution API uses `class-validator`'s `isBase64()` which rejects the `data:` prefix.

**Fix:** Send raw base64 without any prefix:

```python
# Wrong
payload = {"audio": f"data:audio/ogg;base64,{b64}"}

# Correct
payload = {"audio": b64}
```

---

### `not-acceptable` / `SessionError: No sessions` (group send)

**Cause:** Baileys v6.7.12 has a bug in `messages-send.js` where group participant JIDs are encoded using the **group's** domain (`@g.us` → `isLid=false` → `@s.whatsapp.net`) instead of each participant's actual domain (`@lid`). This causes `assertSessions` to request pre-keys for non-existent `@s.whatsapp.net` JIDs.

**Fix — Patch two Baileys files in the container:**

1. `/evolution/node_modules/baileys/lib/Utils/signal.js` — `extractDeviceJids()`:
   - Line 102: `const { user }` → `const { user, server }`
   - Line 110: `{ user, device }` → `{ user, device, server }`

2. `/evolution/node_modules/baileys/lib/Socket/messages-send.js`:
   - Line 325: `isLid ? 'lid' : 's.whatsapp.net'` → `d.server || (isLid ? 'lid' : 's.whatsapp.net')`
   - Line 334: `{ user, device }` → `{ user, device, server: dServer }`
   - Line 335: `isLid ? 'lid' : 's.whatsapp.net'` → `dServer || (isLid ? 'lid' : 's.whatsapp.net')`

This makes each participant use their actual JID domain from the USync query result.

---

### LID contact sends fail with `onWhatsApp` error

**Cause:** Evolution API v2.2.3 validates contacts via `onWhatsApp()`, which returns `exists: false` for `@lid` JIDs. The validation only whitelists `@g.us` and `@broadcast`.

**Fix:** Patch `/evolution/dist/main.js` to also whitelist `@lid`:

```bash
# Find and patch in the running container
docker exec -it msgbot-evolution-api-1 sh
# In the container, at ~line 221350 of /evolution/dist/main.js:
# Change: !n.jid.includes("@broadcast"))throw new f(n)
# To:     !n.jid.includes("@broadcast")&&!n.jid.includes("@lid"))throw new f(n)
```

Then restart the container: `docker restart msgbot-evolution-api-1`

---

### `403` or `409` on instance creation

**Not an error.** Means the instance already exists. The bot code handles this gracefully.

---

## Useful Diagnostic Commands

```bash
# Check connection status
curl -s http://localhost:8085/instance/connectionState/msgbot \
  -H "apikey: $KEY" | python3 -m json.tool

# List all instances
curl -s http://localhost:8085/instance/fetchInstances \
  -H "apikey: $KEY" | python3 -m json.tool

# Check PostgreSQL session data
docker exec msgbot-postgres-1 psql -U evolution -d evolution \
  -c 'SELECT "sessionId", length("creds"), "createdAt" FROM "Session";'

# Fetch group metadata
curl -s "http://localhost:8085/group/findGroupInfos/msgbot?groupJid=120363000000000001@g.us" \
  -H "apikey: $KEY" | python3 -m json.tool

# Bot logs
docker logs msgbot-bot-1 --tail 50

# Evolution API logs
docker logs msgbot-evolution-api-1 --tail 50
```

## Docker Infrastructure

| Service | Image | Data Volume |
|---------|-------|-------------|
| `evolution-api` | `evoapicloud/evolution-api:v2.2.3` + LID patches | `evolution_data:/evolution` |
| `postgres` | `postgres:16-alpine` | `postgres_data:/var/lib/postgresql/data` |
| `bot` | Built from `./Dockerfile` | `bot_data:/app/data` |

PostgreSQL credentials: `evolution:evolution` / database: `evolution`

**Key tables in PostgreSQL:**
- `Session` — Baileys Signal protocol sessions
- `Message` — Message history (if `DATABASE_SAVE_DATA_NEW_MESSAGE=true`)
- `Contact` — Contact cache
- `Chat` — Chat metadata

**Key database in bot (SQLite at `/app/data/msgbot.db`):**
- `chats` — Known chats with settings
- `messages` — Message log
- `whitelist` — Access control
