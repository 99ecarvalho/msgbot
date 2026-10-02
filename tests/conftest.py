# Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>
#
# This file is part of MsgBot. It is free software, licensed under the GNU
# Lesser General Public License v3.0 or later. See COPYING.LESSER and
# COPYING for details.
#
# SPDX-License-Identifier: LGPL-3.0-or-later

"""Test settings: a temporary data directory and known secrets."""
from __future__ import annotations

import os
import tempfile

# Must be set before bot.config is imported anywhere.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="msgbot-test-")
os.environ["WEB_USERNAME"] = "admin"
os.environ["WEB_PASSWORD"] = "test-password"
os.environ["EVOLUTION_API_KEY"] = "test-evolution-key"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
