#!/usr/bin/env bash
# Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>
#
# This file is part of MsgBot. It is free software, licensed under the GNU
# Lesser General Public License v3.0 or later. See COPYING.LESSER and
# COPYING for details.
#
# SPDX-License-Identifier: LGPL-3.0-or-later

set -euo pipefail

cd "$(dirname "$0")"

# The transcriber and TTS services are git submodules in external/; fetch them
# if this checkout was cloned without --recurse-submodules.
if [[ ! -f external/ai-transcriber/Dockerfile || ! -f external/ai-tts/Dockerfile ]]; then
    echo "=== Fetching submodules ==="
    git submodule update --init --recursive
fi

echo "=== Building MsgBot stack ==="
docker compose build "$@"
echo "=== Build complete ==="
