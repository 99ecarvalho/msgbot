# JID Format Reference

WhatsApp identifies contacts and groups using JIDs (Jabber IDs). Since the LID migration (2024+), all new contacts use LID format instead of phone numbers.

## JID Types

| Type | Suffix | Example | Description |
|------|--------|---------|-------------|
| Phone | `@s.whatsapp.net` | `5511900000001@s.whatsapp.net` | Legacy phone-based ID |
| LID | `@lid` | `10000000000001@lid` | Linked Identity — current default |
| Group | `@g.us` | `120363000000000001@g.us` | Group chat |
| Broadcast | `@broadcast` | `status@broadcast` | Status broadcasts |

## LID (Linked Identity)

Since WhatsApp's LID migration, contacts are identified by opaque numeric IDs instead of phone numbers. Key implications:

- **LID numbers are NOT phone numbers** — they cannot be dialed or looked up
- **Typically 14 digits** (e.g., `10000000000001`) but length can vary
- **All webhook `remoteJid` and `participant` fields now use `@lid`**
- **`onWhatsApp()` returns `exists: false` for LID contacts** — they bypass the phone lookup

## createJid Logic

Evolution API's internal `createJid` function converts bare numbers to full JIDs:

```
Input                        → Output
───────────────────────────   ────────────────────────────────
10000000000001@lid            → 10000000000001@lid           (preserved)
120363000000000001@g.us       → 120363000000000001@g.us      (preserved)
5511900000001@s.whatsapp.net  → 5511900000001@s.whatsapp.net (preserved)
120363000000000001            → 120363000000000001@g.us      (≥18 digits → group)
5511900000002-1400000000      → 5511900000002-1400000000@g.us (has dash → group)
10000000000001                → 10000000000001@s.whatsapp.net (WRONG for LID!)
5511900000001                 → 5511900000001@s.whatsapp.net  (correct for phone)
```

> **Critical:** Bare LID numbers (14 digits) are misclassified as phone numbers. Always include `@lid` explicitly.

## How the Bot Handles JIDs

### Storage (SQLite `chats` table)

The bot stores **bare numbers** in `chat_id` (no suffix):

| chat_id | is_group | Type |
|---------|----------|------|
| `10000000000001` | 0 | DM (LID) |
| `120363000000000001` | 1 | Group |
| `5511900000002-1400000000` | 1 | Legacy group |

### Sending (reply route)

When replying, the bot reconstructs the full JID:

```python
if is_group_chat:
    chat_id = f"{chat_id}@g.us"
else:
    chat_id = f"{chat_id}@lid"
```

### Receiving (webhook handler)

The webhook strips the suffix for storage:

```python
phone = remote_jid.split("@")[0]  # "10000000000001@lid" → "10000000000001"
```

## Group Participants

In group messages, the `participant` field identifies the sender:

```json
{
  "key": {
    "remoteJid": "120363000000000001@g.us",
    "participant": "10000000000002@lid"
  }
}
```

The bot extracts `sender_phone = participant.split("@")[0]` for per-person identification within groups.

## Evolution API Validation Patch

Evolution API v2.2.3 has a bug: `sendMessageWithTyping()` calls `onWhatsApp()` for all JIDs, which returns `exists: false` for `@lid` contacts. The validation then throws an error because only `@g.us` and `@broadcast` were whitelisted.

**Patch applied** in `/evolution/dist/main.js` (in-container):

```diff
- !n.jid.includes("@broadcast")) throw new f(n)
+ !n.jid.includes("@broadcast") && !n.jid.includes("@lid")) throw new f(n)
```

This allows `@lid` contacts to bypass the `onWhatsApp` existence check.

> **Note:** This patch is in the running container only. It will be lost on container recreation unless persisted via Dockerfile or volume mount.
