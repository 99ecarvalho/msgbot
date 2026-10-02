# Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>
#
# This file is part of MsgBot. It is free software, licensed under the GNU
# Lesser General Public License v3.0 or later. See COPYING.LESSER and
# COPYING for details.
#
# SPDX-License-Identifier: LGPL-3.0-or-later

"""Weekly message history on the Stats page."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from bot import db


def _ts(day: str) -> float:
    return datetime.fromisoformat(day).replace(hour=12, tzinfo=timezone.utc).timestamp()


def test_weekly_history_groups_iso_weeks_newest_first_with_gaps():
    async def run():
        conn = await db.get_db()
        try:
            await conn.execute("DELETE FROM messages")
            await conn.execute("DELETE FROM chats")
            await conn.execute(
                "INSERT INTO chats (id, platform, chat_id, created_at) VALUES (1, 'whatsapp', 'x', 0)")
            # 2025-12-29 (Mon) and 2026-01-04 (Sun) are both ISO week 2026-W01;
            # 2025-12-28 (Sun) is 2025-W52. Nothing in 2026-W02, 3 in 2026-W03.
            days = ["2025-12-28", "2025-12-29", "2026-01-04", "2026-01-12", "2026-01-13", "2026-01-18"]
            for d in days:
                await conn.execute(
                    "INSERT INTO messages (chat_rowid, direction, msg_type, created_at) VALUES (1, 'in', 'text', ?)",
                    (_ts(d),))
            await conn.commit()
            return await db.get_weekly_history()
        finally:
            await db.close_db()

    weeks = asyncio.run(run())
    assert [(w["week"], w["cnt"]) for w in weeks] == [
        ("2026-W03", 3), ("2026-W02", 0), ("2026-W01", 2), ("2025-W52", 1),
    ]
    assert weeks[0]["start"] == "2026-01-12"
