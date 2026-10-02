# Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>
#
# This file is part of MsgBot. It is free software, licensed under the GNU
# Lesser General Public License v3.0 or later. See COPYING.LESSER and
# COPYING for details.
#
# SPDX-License-Identifier: LGPL-3.0-or-later

"""Webhook registration keeps retrying until the service is reachable."""
from __future__ import annotations

import asyncio

from bot import db
from bot.main import _retry_setup


def test_setup_is_retried_until_it_succeeds():
    calls = []

    async def flaky_setup():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("Evolution API is still starting")

    async def run():
        try:
            await asyncio.wait_for(_retry_setup("evolution", flaky_setup, delay=0.01), timeout=5)
        finally:
            await db.close_db()

    asyncio.run(run())
    assert len(calls) == 3
