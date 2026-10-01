#!/usr/bin/env bash
# Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>
#
# This file is part of MsgBot. It is free software, licensed under the GNU
# Lesser General Public License v3.0 or later. See COPYING.LESSER and
# COPYING for details.
#
# SPDX-License-Identifier: LGPL-3.0-or-later

set -euo pipefail

echo "=== Building MsgBot stack ==="
docker compose build "$@"
echo "=== Build complete ==="
