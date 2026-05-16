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

### `not-acceptable` (group send)

**Cause:** Baileys cannot establish SenderKey encryption sessions with group participants. Typically happens after a logout/re-pair.

**Symptoms:**
- DM sending works fine
- Group sending returns `400 Bad Request` with `not-acceptable`
- The `Session` table in PostgreSQL has only the main credentials row

**Workarounds:**
1. Send a DM to each group participant first — forces per-contact session establishment
2. Wait for incoming group messages to trigger session rebuild
3. As a last resort, delete and recreate the instance

**Check sessions:**
```bash
docker exec msgbot-postgres-1 psql -U evolution -d evolution \
  -c 'SELECT "sessionId", length("creds") as size, "createdAt" FROM "Session" ORDER BY "createdAt" DESC;'
```

---

### `SessionError: No sessions` (Baileys)

**Cause:** Same as above — per-participant Signal protocol sessions are missing.

**Details:** After logout, the Baileys session store is wiped. Only the main credential row remains. The per-participant sessions (needed for end-to-end encryption) must be re-established.

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
| `evolution-api` | `atendai/evolution-api:v2.2.3` | `evolution_data:/evolution` |
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
