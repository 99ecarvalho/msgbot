"""SQLite database layer — aiosqlite."""
from __future__ import annotations

import json
import time
from pathlib import Path

import aiosqlite

from bot.config import settings

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _db = await aiosqlite.connect(str(settings.db_path))
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
        await _init_tables(_db)
    return _db


async def close_db():
    global _db
    if _db:
        await _db.close()
        _db = None


async def _init_tables(db: aiosqlite.Connection):
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS chats (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            platform    TEXT NOT NULL,          -- telegram | whatsapp
            chat_id     TEXT NOT NULL,          -- platform-specific chat id (phone or group JID)
            display_name TEXT DEFAULT '',       -- pushName / user first name
            group_name  TEXT DEFAULT '',        -- group/channel name if applicable
            is_group    INTEGER DEFAULT 0,      -- 1 if group/channel chat
            system_prompt TEXT DEFAULT '',      -- empty = use global default
            response_mode TEXT DEFAULT '',      -- empty = use global default
            created_at  REAL NOT NULL,
            UNIQUE(platform, chat_id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_rowid   INTEGER NOT NULL REFERENCES chats(id),
            direction    TEXT NOT NULL,         -- in | out
            msg_type     TEXT NOT NULL,         -- voice | text
            content_text TEXT DEFAULT '',
            audio_path   TEXT DEFAULT '',
            transcription TEXT DEFAULT '',
            llm_response TEXT DEFAULT '',
            sender_name  TEXT DEFAULT '',       -- who sent the message (pushName / display)
            sender_phone TEXT DEFAULT '',       -- sender phone (esp. for group messages)
            device       TEXT DEFAULT '',       -- android | ios | web | desktop | unknown
            blocked      INTEGER DEFAULT 0,     -- 1 if message was blocked (not whitelisted)
            created_at   REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS config (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS logs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            level      TEXT NOT NULL,
            source     TEXT DEFAULT '',
            message    TEXT NOT NULL,
            extra_json TEXT DEFAULT '{}',
            created_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_rowid);
        CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
        CREATE INDEX IF NOT EXISTS idx_logs_created ON logs(created_at);

        CREATE TABLE IF NOT EXISTS whitelist (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            platform    TEXT NOT NULL DEFAULT '',  -- telegram | whatsapp | '' (any)
            filter_type TEXT NOT NULL,             -- phone | contact_name | channel
            value       TEXT NOT NULL,             -- the phone number, name, or channel name
            enabled     INTEGER NOT NULL DEFAULT 1,
            notes       TEXT DEFAULT '',
            created_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS workflows (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            description TEXT DEFAULT '',
            enabled     INTEGER DEFAULT 1,
            created_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS workflow_steps (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id INTEGER NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            step_order  INTEGER NOT NULL,
            step_type   TEXT NOT NULL,
            label       TEXT DEFAULT '',
            config_json TEXT DEFAULT '{}',
            condition   TEXT DEFAULT '',
            enabled     INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS whitelist_workflows (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            whitelist_id INTEGER NOT NULL REFERENCES whitelist(id) ON DELETE CASCADE,
            workflow_id  INTEGER NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            UNIQUE(whitelist_id, workflow_id)
        );

        CREATE TABLE IF NOT EXISTS workflow_logs (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id         TEXT DEFAULT '',
            message_id     INTEGER,
            workflow_id    INTEGER NOT NULL,
            step_id        INTEGER,
            step_order     INTEGER,
            step_type      TEXT NOT NULL,
            input_summary  TEXT DEFAULT '',
            output_summary TEXT DEFAULT '',
            status         TEXT NOT NULL,
            error_text     TEXT DEFAULT '',
            elapsed_ms     INTEGER DEFAULT 0,
            created_at     REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_wf_logs_run ON workflow_logs(run_id);
        CREATE INDEX IF NOT EXISTS idx_wf_logs_msg ON workflow_logs(message_id);

        CREATE TABLE IF NOT EXISTS llm_logs (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id        TEXT DEFAULT '',
            sender_phone   TEXT DEFAULT '',
            model          TEXT DEFAULT '',
            system_prompt  TEXT DEFAULT '',
            user_message   TEXT DEFAULT '',
            assistant_reply TEXT DEFAULT '',
            prompt_tokens  INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens   INTEGER DEFAULT 0,
            elapsed_ms     INTEGER DEFAULT 0,
            created_at     REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_llm_logs_created ON llm_logs(created_at);
    """)
    await db.commit()

    # Migrations for existing DBs
    try:
        await db.execute("ALTER TABLE chats ADD COLUMN group_name TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        await db.execute("ALTER TABLE chats ADD COLUMN is_group INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        await db.execute("ALTER TABLE messages ADD COLUMN sender_name TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        await db.execute("ALTER TABLE messages ADD COLUMN sender_phone TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        await db.execute("ALTER TABLE messages ADD COLUMN device TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        await db.execute("ALTER TABLE messages ADD COLUMN blocked INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        await db.execute("ALTER TABLE whitelist ADD COLUMN display_name TEXT DEFAULT ''")
    except Exception:
        pass
    # New whitelist model columns
    try:
        await db.execute("ALTER TABLE whitelist ADD COLUMN entry_type TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        await db.execute("ALTER TABLE whitelist ADD COLUMN phone TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        await db.execute("ALTER TABLE whitelist ADD COLUMN group_id TEXT DEFAULT ''")
    except Exception:
        pass
    await db.commit()

    # Migrate old whitelist entries (filter_type/value → entry_type/phone/group_id)
    old_entries = await db.execute_fetchall(
        "SELECT id, filter_type, value FROM whitelist WHERE entry_type = ''"
    )
    for row in old_entries:
        ft, val = row["filter_type"], row["value"]
        if ft == "phone":
            # Heuristic: ≤13 digits = real phone → person; longer = group JID → group
            digits = val.lstrip("+")
            if digits.isdigit() and len(digits) <= 13:
                await db.execute(
                    "UPDATE whitelist SET entry_type='person', phone=? WHERE id=?",
                    (val, row["id"]),
                )
            else:
                await db.execute(
                    "UPDATE whitelist SET entry_type='group', group_id=? WHERE id=?",
                    (val, row["id"]),
                )
        elif ft == "channel":
            await db.execute(
                "UPDATE whitelist SET entry_type='group', group_id=? WHERE id=?",
                (val, row["id"]),
            )
        else:
            # contact_name → person with display_name
            await db.execute(
                "UPDATE whitelist SET entry_type='person', display_name=? WHERE id=?",
                (val, row["id"]),
            )
    await db.commit()

    # Seed default workflows if none exist
    await seed_default_workflows()


# ---- Chat helpers ----

async def get_or_create_chat(
    platform: str, chat_id: str, display_name: str = "",
    group_name: str = "", is_group: bool = False,
) -> dict:
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT * FROM chats WHERE platform=? AND chat_id=?", (platform, chat_id)
    )
    if row:
        chat = dict(row[0])
        # Update display_name / group_name if they changed
        updates = {}
        if display_name and display_name != chat.get("display_name"):
            updates["display_name"] = display_name
        if group_name and group_name != chat.get("group_name"):
            updates["group_name"] = group_name
        if is_group and not chat.get("is_group"):
            updates["is_group"] = 1
        if updates:
            await update_chat(chat["id"], **updates)
            chat.update(updates)
        return chat
    now = time.time()
    cursor = await db.execute(
        "INSERT INTO chats (platform, chat_id, display_name, group_name, is_group, system_prompt, response_mode, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (platform, chat_id, display_name, group_name, 1 if is_group else 0, "", "", now),
    )
    await db.commit()
    return {
        "id": cursor.lastrowid, "platform": platform, "chat_id": chat_id,
        "display_name": display_name, "group_name": group_name, "is_group": 1 if is_group else 0,
        "system_prompt": "", "response_mode": "", "created_at": now,
    }


async def update_chat(chat_rowid: int, **kwargs):
    db = await get_db()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [chat_rowid]
    await db.execute(f"UPDATE chats SET {sets} WHERE id=?", vals)
    await db.commit()


async def get_all_chats() -> list[dict]:
    db = await get_db()
    rows = await db.execute_fetchall("SELECT * FROM chats ORDER BY created_at DESC")
    return [dict(r) for r in rows]


async def get_chat(chat_rowid: int) -> dict | None:
    db = await get_db()
    rows = await db.execute_fetchall("SELECT * FROM chats WHERE id=?", (chat_rowid,))
    return dict(rows[0]) if rows else None


# ---- Message helpers ----

async def save_message(
    chat_rowid: int,
    direction: str,
    msg_type: str,
    content_text: str = "",
    audio_path: str = "",
    transcription: str = "",
    llm_response: str = "",
    sender_name: str = "",
    sender_phone: str = "",
    device: str = "",
    blocked: bool = False,
) -> int:
    db = await get_db()
    now = time.time()
    cursor = await db.execute(
        "INSERT INTO messages (chat_rowid, direction, msg_type, content_text, audio_path, transcription, llm_response, sender_name, sender_phone, device, blocked, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (chat_rowid, direction, msg_type, content_text, audio_path, transcription, llm_response, sender_name, sender_phone, device, int(blocked), now),
    )
    await db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


async def update_message(msg_id: int, **kwargs):
    db = await get_db()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [msg_id]
    await db.execute(f"UPDATE messages SET {sets} WHERE id=?", vals)
    await db.commit()


async def get_message(msg_id: int) -> dict | None:
    db = await get_db()
    rows = await db.execute_fetchall("SELECT * FROM messages WHERE id=?", (msg_id,))
    return dict(rows[0]) if rows else None


async def get_messages(chat_rowid: int | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    db = await get_db()
    if chat_rowid:
        rows = await db.execute_fetchall(
            "SELECT m.*, c.platform, c.chat_id, c.display_name, c.group_name, c.is_group FROM messages m JOIN chats c ON m.chat_rowid=c.id WHERE m.chat_rowid=? ORDER BY m.created_at DESC LIMIT ? OFFSET ?",
            (chat_rowid, limit, offset),
        )
    else:
        rows = await db.execute_fetchall(
            "SELECT m.*, c.platform, c.chat_id, c.display_name, c.group_name, c.is_group FROM messages m JOIN chats c ON m.chat_rowid=c.id ORDER BY m.created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
    # Enrich: for group messages use sender info over chat-level display_name
    result = []
    for r in rows:
        d = dict(r)
        d["effective_sender"] = d.get("sender_name") or d.get("display_name") or ""
        d["effective_phone"] = d.get("sender_phone") or d.get("chat_id") or ""
        result.append(d)
    return result
    return [dict(r) for r in rows]


# ---- Stats helpers ----

async def get_stats() -> dict:
    db = await get_db()
    r = {}
    # Total messages
    rows = await db.execute_fetchall("SELECT COUNT(*) as cnt FROM messages")
    r["total_messages"] = rows[0]["cnt"]
    # By direction
    rows = await db.execute_fetchall("SELECT direction, COUNT(*) as cnt FROM messages GROUP BY direction")
    r["messages_in"] = 0
    r["messages_out"] = 0
    for row in rows:
        if row["direction"] == "in":
            r["messages_in"] = row["cnt"]
        else:
            r["messages_out"] = row["cnt"]
    # By type
    rows = await db.execute_fetchall("SELECT msg_type, COUNT(*) as cnt FROM messages GROUP BY msg_type")
    r["messages_voice"] = 0
    r["messages_text"] = 0
    for row in rows:
        if row["msg_type"] == "voice":
            r["messages_voice"] = row["cnt"]
        else:
            r["messages_text"] = row["cnt"]
    # By platform
    rows = await db.execute_fetchall(
        "SELECT c.platform, COUNT(*) as cnt FROM messages m JOIN chats c ON m.chat_rowid=c.id GROUP BY c.platform"
    )
    r["by_platform"] = {row["platform"]: row["cnt"] for row in rows}
    # Total chats
    rows = await db.execute_fetchall("SELECT COUNT(*) as cnt FROM chats")
    r["total_chats"] = rows[0]["cnt"]
    # Group vs DM
    rows = await db.execute_fetchall("SELECT is_group, COUNT(*) as cnt FROM chats GROUP BY is_group")
    r["chats_group"] = 0
    r["chats_dm"] = 0
    for row in rows:
        if row["is_group"]:
            r["chats_group"] = row["cnt"]
        else:
            r["chats_dm"] = row["cnt"]
    # Audio files: count and total size
    audio_count = 0
    audio_size = 0
    rows = await db.execute_fetchall("SELECT audio_path FROM messages WHERE audio_path != ''")
    audios_dir = settings.audios_dir
    for row in rows:
        audio_count += 1
        p = audios_dir.parent / row["audio_path"]
        if p.exists():
            audio_size += p.stat().st_size
    r["audio_count"] = audio_count
    r["audio_size_mb"] = round(audio_size / (1024 * 1024), 2)
    # Transcriptions generated
    rows = await db.execute_fetchall("SELECT COUNT(*) as cnt FROM messages WHERE transcription != ''")
    r["transcriptions"] = rows[0]["cnt"]
    # LLM responses
    rows = await db.execute_fetchall("SELECT COUNT(*) as cnt FROM messages WHERE llm_response != ''")
    r["llm_responses"] = rows[0]["cnt"]
    # Whitelist
    rows = await db.execute_fetchall("SELECT COUNT(*) as cnt FROM whitelist WHERE enabled=1")
    r["whitelist_active"] = rows[0]["cnt"]
    # Blocked messages
    rows = await db.execute_fetchall("SELECT COUNT(*) as cnt FROM messages WHERE content_text LIKE '%[BLOCKED%'")
    r["blocked_messages"] = rows[0]["cnt"]
    # Top chats by message count
    rows = await db.execute_fetchall(
        "SELECT c.id, c.platform, c.chat_id, c.display_name, c.group_name, c.is_group, COUNT(*) as cnt "
        "FROM messages m JOIN chats c ON m.chat_rowid=c.id GROUP BY c.id ORDER BY cnt DESC LIMIT 10"
    )
    r["top_chats"] = [dict(row) for row in rows]
    # Messages per day (last 14 days)
    rows = await db.execute_fetchall(
        "SELECT date(created_at, 'unixepoch') as day, COUNT(*) as cnt "
        "FROM messages WHERE created_at > ? GROUP BY day ORDER BY day",
        (time.time() - 14 * 86400,)
    )
    r["daily"] = [dict(row) for row in rows]
    return r


# ---- Config helpers ----

async def get_config(key: str, default: str = "") -> str:
    db = await get_db()
    rows = await db.execute_fetchall("SELECT value FROM config WHERE key=?", (key,))
    return rows[0]["value"] if rows else default


async def set_config(key: str, value: str):
    db = await get_db()
    await db.execute(
        "INSERT INTO config (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    await db.commit()


async def get_all_config() -> dict[str, str]:
    db = await get_db()
    rows = await db.execute_fetchall("SELECT key, value FROM config")
    return {r["key"]: r["value"] for r in rows}


# ---- Log helpers ----

async def save_log(level: str, message: str, source: str = "", extra: dict | None = None):
    db = await get_db()
    await db.execute(
        "INSERT INTO logs (level, source, message, extra_json, created_at) VALUES (?,?,?,?,?)",
        (level, source, message, json.dumps(extra or {}), time.time()),
    )
    await db.commit()


async def get_logs(limit: int = 200, level: str | None = None) -> list[dict]:
    db = await get_db()
    if level:
        rows = await db.execute_fetchall(
            "SELECT * FROM logs WHERE level=? ORDER BY created_at DESC LIMIT ?", (level, limit)
        )
    else:
        rows = await db.execute_fetchall(
            "SELECT * FROM logs ORDER BY created_at DESC LIMIT ?", (limit,)
        )
    return [dict(r) for r in rows]


# ---- LLM log helpers ----

async def save_llm_log(
    model: str = "",
    system_prompt: str = "",
    user_message: str = "",
    assistant_reply: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    elapsed_ms: int = 0,
    chat_id: str = "",
    sender_phone: str = "",
) -> int:
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO llm_logs (chat_id, sender_phone, model, system_prompt, user_message, assistant_reply, prompt_tokens, completion_tokens, total_tokens, elapsed_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (chat_id, sender_phone, model, system_prompt, user_message, assistant_reply, prompt_tokens, completion_tokens, total_tokens, elapsed_ms, time.time()),
    )
    await db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


async def get_llm_logs(limit: int = 100) -> list[dict]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM llm_logs ORDER BY created_at DESC LIMIT ?", (limit,)
    )
    return [dict(r) for r in rows]


async def get_llm_stats() -> dict:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT COUNT(*) as cnt, COALESCE(SUM(prompt_tokens),0) as total_prompt, "
        "COALESCE(SUM(completion_tokens),0) as total_completion, "
        "COALESCE(SUM(total_tokens),0) as total_tokens FROM llm_logs"
    )
    r = dict(rows[0])
    return r


async def clear_llm_logs():
    db = await get_db()
    await db.execute("DELETE FROM llm_logs")
    await db.commit()


# ---- Whitelist helpers ----

async def add_whitelist_entry(
    entry_type: str,       # person | group | person_in_group
    platform: str = "",
    phone: str = "",
    group_id: str = "",
    display_name: str = "",
    notes: str = "",
) -> int:
    db = await get_db()
    now = time.time()
    cursor = await db.execute(
        "INSERT INTO whitelist (platform, filter_type, value, entry_type, phone, group_id, display_name, enabled, notes, created_at) "
        "VALUES (?,?,?,?,?,?,?,1,?,?)",
        (platform, entry_type, phone or group_id, entry_type, phone, group_id, display_name, notes, now),
    )
    await db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


async def remove_whitelist_entry(entry_id: int):
    db = await get_db()
    await db.execute("DELETE FROM whitelist WHERE id=?", (entry_id,))
    await db.commit()


async def toggle_whitelist_entry(entry_id: int, enabled: bool):
    db = await get_db()
    await db.execute("UPDATE whitelist SET enabled=? WHERE id=?", (1 if enabled else 0, entry_id))
    await db.commit()


async def get_whitelist() -> list[dict]:
    db = await get_db()
    rows = await db.execute_fetchall("SELECT * FROM whitelist ORDER BY created_at DESC")
    return [dict(r) for r in rows]


async def is_whitelisted(
    platform: str,
    chat_id: str,
    is_group: bool = False,
    sender_phone: str = "",
) -> dict | None:
    """Check if a message is whitelisted.

    Three entry types:
      person          – matches DMs from this phone
      group           – matches ALL messages in this group
      person_in_group – matches ONE person in ONE group

    Returns the matching whitelist entry dict, or None if blocked.
    """
    db = await get_db()
    rows = await db.execute_fetchall("SELECT * FROM whitelist WHERE enabled=1")
    if not rows:
        return None
    for row in rows:
        r = dict(row)
        # Platform filter
        if r["platform"] and r["platform"] != platform:
            continue
        et = r.get("entry_type") or r.get("filter_type", "")
        if et == "person" and not is_group:
            # DM: match by phone
            if r.get("phone") and r["phone"] == chat_id:
                return r
            if r.get("phone") and sender_phone and r["phone"] == sender_phone:
                return r
        elif et == "group" and is_group:
            # Entire group whitelisted
            if r.get("group_id") and r["group_id"] == chat_id:
                return r
        elif et == "person_in_group" and is_group:
            # Specific person in specific group
            if (r.get("group_id") and r["group_id"] == chat_id
                    and r.get("phone") and sender_phone
                    and r["phone"] == sender_phone):
                return r
    return None


# ---- Workflow helpers ----

async def create_workflow(name: str, description: str = "", enabled: int = 0) -> int:
    db = await get_db()
    now = time.time()
    cursor = await db.execute(
        "INSERT INTO workflows (name, description, enabled, created_at) VALUES (?,?,?,?)",
        (name, description, enabled, now),
    )
    await db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


async def get_workflow(workflow_id: int) -> dict | None:
    db = await get_db()
    rows = await db.execute_fetchall("SELECT * FROM workflows WHERE id=?", (workflow_id,))
    return dict(rows[0]) if rows else None


async def get_all_workflows() -> list[dict]:
    db = await get_db()
    rows = await db.execute_fetchall("SELECT * FROM workflows ORDER BY created_at DESC")
    return [dict(r) for r in rows]


async def update_workflow(workflow_id: int, **kwargs):
    db = await get_db()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [workflow_id]
    await db.execute(f"UPDATE workflows SET {sets} WHERE id=?", vals)
    await db.commit()


async def delete_workflow(workflow_id: int):
    db = await get_db()
    await db.execute("DELETE FROM workflow_steps WHERE workflow_id=?", (workflow_id,))
    await db.execute("DELETE FROM whitelist_workflows WHERE workflow_id=?", (workflow_id,))
    await db.execute("DELETE FROM workflows WHERE id=?", (workflow_id,))
    await db.commit()


async def add_workflow_step(
    workflow_id: int, step_order: int, step_type: str,
    label: str = "", config_json: str = "{}", condition: str = "",
) -> int:
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO workflow_steps (workflow_id, step_order, step_type, label, config_json, condition, enabled) VALUES (?,?,?,?,?,?,1)",
        (workflow_id, step_order, step_type, label, config_json, condition),
    )
    await db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


async def update_workflow_step(step_id: int, **kwargs):
    db = await get_db()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [step_id]
    await db.execute(f"UPDATE workflow_steps SET {sets} WHERE id=?", vals)
    await db.commit()


async def delete_workflow_step(step_id: int):
    db = await get_db()
    await db.execute("DELETE FROM workflow_steps WHERE id=?", (step_id,))
    await db.commit()


async def get_workflow_steps(workflow_id: int) -> list[dict]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM workflow_steps WHERE workflow_id=? ORDER BY step_order",
        (workflow_id,),
    )
    return [dict(r) for r in rows]


async def get_workflow_with_steps(workflow_id: int) -> dict | None:
    wf = await get_workflow(workflow_id)
    if not wf:
        return None
    wf["steps"] = await get_workflow_steps(workflow_id)
    return wf


# ---- Whitelist <-> Workflow links ----

async def link_whitelist_workflow(whitelist_id: int, workflow_id: int):
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO whitelist_workflows (whitelist_id, workflow_id) VALUES (?,?)",
        (whitelist_id, workflow_id),
    )
    await db.commit()


async def unlink_whitelist_workflow(whitelist_id: int, workflow_id: int):
    db = await get_db()
    await db.execute(
        "DELETE FROM whitelist_workflows WHERE whitelist_id=? AND workflow_id=?",
        (whitelist_id, workflow_id),
    )
    await db.commit()


async def get_workflows_for_whitelist(whitelist_id: int) -> list[dict]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT w.* FROM workflows w JOIN whitelist_workflows ww ON w.id=ww.workflow_id "
        "WHERE ww.whitelist_id=? AND w.enabled=1 ORDER BY w.name",
        (whitelist_id,),
    )
    return [dict(r) for r in rows]


async def get_workflows_for_whitelist_entry(whitelist_id: int) -> list[dict]:
    """Get ALL workflows linked to a whitelist entry (regardless of enabled)."""
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT w.* FROM workflows w JOIN whitelist_workflows ww ON w.id=ww.workflow_id "
        "WHERE ww.whitelist_id=? ORDER BY w.name",
        (whitelist_id,),
    )
    return [dict(r) for r in rows]


async def get_whitelist_entries_for_workflow(workflow_id: int) -> list[dict]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT wl.* FROM whitelist wl JOIN whitelist_workflows ww ON wl.id=ww.whitelist_id "
        "WHERE ww.workflow_id=?",
        (workflow_id,),
    )
    return [dict(r) for r in rows]


# ---- Workflow logs ----

async def save_workflow_log(
    run_id: str, message_id: int | None, workflow_id: int,
    step_id: int | None, step_order: int, step_type: str,
    input_summary: str = "", output_summary: str = "",
    status: str = "ok", error_text: str = "", elapsed_ms: int = 0,
) -> int:
    db = await get_db()
    now = time.time()
    cursor = await db.execute(
        "INSERT INTO workflow_logs (run_id, message_id, workflow_id, step_id, step_order, step_type, "
        "input_summary, output_summary, status, error_text, elapsed_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, message_id, workflow_id, step_id, step_order, step_type,
         input_summary, output_summary, status, error_text, elapsed_ms, now),
    )
    await db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


async def get_workflow_logs(
    workflow_id: int | None = None, message_id: int | None = None,
    run_id: str | None = None, limit: int = 100,
) -> list[dict]:
    db = await get_db()
    clauses = []
    params: list = []
    if workflow_id:
        clauses.append("workflow_id=?")
        params.append(workflow_id)
    if message_id:
        clauses.append("message_id=?")
        params.append(message_id)
    if run_id:
        clauses.append("run_id=?")
        params.append(run_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    rows = await db.execute_fetchall(
        f"SELECT * FROM workflow_logs{where} ORDER BY created_at DESC LIMIT ?", params
    )
    return [dict(r) for r in rows]


async def seed_default_workflows():
    """Create default workflows if none exist."""
    from bot.config import settings
    import json
    db = await get_db()
    rows = await db.execute_fetchall("SELECT COUNT(*) as cnt FROM workflows")
    if rows[0]["cnt"] > 0:
        return

    llm_config = json.dumps({"prompt": settings.default_system_prompt})

    # Default Text Bot — processes text messages only
    wf1 = await create_workflow(
        "Default Text Bot",
        "Process text messages with LLM and reply with text",
        enabled=0,
    )
    await add_workflow_step(wf1, 1, "llm", label="Process with LLM", config_json=llm_config, condition="has_text")
    await add_workflow_step(wf1, 2, "save", label="Save to Database")
    await add_workflow_step(wf1, 3, "reply_text", label="Reply with Text", condition="has_text")

    # Default Mixed Bot — handles both text and voice input
    wf2 = await create_workflow(
        "Default Mixed Bot",
        "Transcribe audio if present, process with LLM, reply with text (and audio for voice messages)",
        enabled=0,
    )
    await add_workflow_step(wf2, 1, "transcribe", label="Transcribe Audio", condition="has_audio")
    await add_workflow_step(wf2, 2, "llm", label="Process with LLM", config_json=llm_config)
    await add_workflow_step(wf2, 3, "save", label="Save to Database")
    await add_workflow_step(wf2, 4, "reply_text", label="Reply with Text")
    await add_workflow_step(wf2, 5, "reply_audio", label="Reply with Audio", condition="mode_auto_voice")

    # Audio Summary Bot — transcribes audio, summarizes with executive paragraph + bullet points
    summary_prompt = json.dumps({"prompt": (
        "Você é um assistente especializado em resumir mensagens de voz. "
        "Ao receber a transcrição de um áudio, produza:\n"
        "1. Um parágrafo executivo curto (2-3 frases) com o ponto principal.\n"
        "2. Bullet points com os detalhes relevantes.\n\n"
        "Responda sempre em português. Seja conciso e objetivo."
    )})
    wf3 = await create_workflow(
        "Audio Summary Bot",
        "Transcreve áudio, resume com parágrafo executivo + bullet points, responde texto e áudio",
        enabled=0,
    )
    await add_workflow_step(wf3, 1, "transcribe", label="Transcrever Áudio", condition="has_audio")
    await add_workflow_step(wf3, 2, "reply_text", label="Enviar Transcrição")
    await add_workflow_step(wf3, 3, "llm", label="Resumir com LLM", config_json=summary_prompt)
    await add_workflow_step(wf3, 4, "save", label="Salvar no Banco")
    await add_workflow_step(wf3, 5, "reply_text", label="Responder Resumo")
    await add_workflow_step(wf3, 6, "reply_audio", label="Responder Áudio (TTS)")


# ---- Database maintenance ----

async def clear_messages():
    db = await get_db()
    await db.execute("DELETE FROM messages")
    await db.commit()


async def clear_logs():
    db = await get_db()
    await db.execute("DELETE FROM logs")
    await db.commit()


async def clear_chats():
    db = await get_db()
    await db.execute("DELETE FROM messages")
    await db.execute("DELETE FROM chats")
    await db.commit()


async def clear_whitelist():
    db = await get_db()
    await db.execute("DELETE FROM whitelist")
    await db.commit()


async def clear_config():
    db = await get_db()
    await db.execute("DELETE FROM config")
    await db.commit()


async def clear_all():
    db = await get_db()
    await db.execute("DELETE FROM messages")
    await db.execute("DELETE FROM chats")
    await db.execute("DELETE FROM logs")
    await db.execute("DELETE FROM llm_logs")
    await db.execute("DELETE FROM whitelist")
    await db.execute("DELETE FROM config")
    await db.commit()
