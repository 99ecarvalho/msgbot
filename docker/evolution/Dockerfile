# Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>
#
# This file is part of MsgBot. It is free software, licensed under the GNU
# Lesser General Public License v3.0 or later. See COPYING.LESSER and
# COPYING for details.
#
# SPDX-License-Identifier: LGPL-3.0-or-later

# Evolution API v2.2.3 (Baileys 6.7.12). The project moved its images from
# atendai/ to evoapicloud/; the old name no longer exists on Docker Hub. Pinned
# by digest so a re-pushed tag can't change what gets patched.
FROM evoapicloud/evolution-api:v2.2.3@sha256:7e5aab8844cadf499bd8afe4b15e3fde3f0f85de6ab4ccae611197af03ab11ef

# Apply LID patches for Baileys 6.7.12
COPY apply-patches.js /tmp/apply-patches.js
RUN node /tmp/apply-patches.js && rm /tmp/apply-patches.js
